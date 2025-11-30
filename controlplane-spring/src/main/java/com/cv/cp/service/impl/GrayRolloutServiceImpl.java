package com.cv.cp.service.impl;

import com.cv.cp.grpc.VideoAnalyzerClient;
import com.cv.cp.service.GrayRolloutService;
import com.cv.cp.service.ModelAliasService;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.locks.ReentrantLock;
import org.springframework.stereotype.Service;

@Service
public class GrayRolloutServiceImpl implements GrayRolloutService {

  private static final class GrayTarget {
    final String pipeline;
    final String node;

    GrayTarget(String pipeline, String node) {
      this.pipeline = pipeline;
      this.node = node;
    }
  }

  private static final class GrayPlan {
    final ReentrantLock lock = new ReentrantLock();
    final String id;
    final String alias;
    final int batchSize;
    final int intervalMs;
    final List<GrayTarget> targets;
    final List<String> events = new ArrayList<>();
    int applied;
    boolean running;
    boolean done;
    String error;

    GrayPlan(String id, String alias, int batchSize, int intervalMs, List<GrayTarget> targets) {
      this.id = id;
      this.alias = alias;
      this.batchSize = batchSize;
      this.intervalMs = intervalMs;
      this.targets = targets;
    }
  }

  private final ConcurrentHashMap<String, GrayPlan> plans = new ConcurrentHashMap<>();
  private final ExecutorService executor = Executors.newCachedThreadPool();
  private final ModelAliasService modelAliasService;
  private final VideoAnalyzerClient videoAnalyzerClient;

  public GrayRolloutServiceImpl(
      ModelAliasService modelAliasService,
      VideoAnalyzerClient videoAnalyzerClient) {
    this.modelAliasService = modelAliasService;
    this.videoAnalyzerClient = videoAnalyzerClient;
  }

  @Override
  public Map<String, Object> start(Map<String, Object> payload) {
    String alias = stringOrDefault(payload.get("alias"), "canary");
    int batch = intOrDefault(payload.get("batch_size"), 1);
    int interval = intOrDefault(payload.get("interval_ms"), 30_000);
    Object tsObj = payload.get("targets");
    if (!(tsObj instanceof List<?> list)) {
      throw new IllegalArgumentException("targets required");
    }
    List<GrayTarget> targets = new ArrayList<>();
    for (Object o : list) {
      if (!(o instanceof Map<?, ?> m)) {
        continue;
      }
      Object p = m.get("pipeline");
      Object n = m.get("node");
      if (p instanceof String ps && n instanceof String ns && !ps.isEmpty() && !ns.isEmpty()) {
        targets.add(new GrayTarget(ps, ns));
      }
    }
    if (targets.isEmpty()) {
      throw new IllegalArgumentException("targets required");
    }
    String id = UUID.randomUUID().toString();
    GrayPlan plan =
        new GrayPlan(id, alias, Math.max(1, batch), Math.max(0, interval), targets);
    plans.put(id, plan);
    executor.execute(() -> runPlan(plan));
    Map<String, Object> data = new HashMap<>();
    data.put("id", id);
    data.put("events", "/api/deploy/gray/events?id=" + id);
    Map<String, Object> out = new HashMap<>();
    out.put("code", "ACCEPTED");
    out.put("data", data);
    return out;
  }

  @Override
  public Map<String, Object> status(String id) {
    GrayPlan p = plans.get(id);
    if (p == null) {
      return null;
    }
    Map<String, Object> d = new HashMap<>();
    p.lock.lock();
    try {
      d.put("id", p.id);
      d.put("alias", p.alias);
      d.put("applied", p.applied);
      d.put("total", p.targets.size());
      d.put("running", p.running);
      d.put("done", p.done);
      if (p.error != null && !p.error.isEmpty()) {
        d.put("error", p.error);
      }
    } finally {
      p.lock.unlock();
    }
    Map<String, Object> out = new HashMap<>();
    out.put("code", "OK");
    out.put("data", d);
    return out;
  }

  @Override
  public List<String> consumeEvents(String id, int fromIndex) {
    GrayPlan p = plans.get(id);
    if (p == null) {
      return null;
    }
    p.lock.lock();
    try {
      if (fromIndex >= p.events.size()) {
        return Collections.emptyList();
      }
      return new ArrayList<>(p.events.subList(fromIndex, p.events.size()));
    } finally {
      p.lock.unlock();
    }
  }

  private void runPlan(GrayPlan plan) {
    emit(plan, "state", Map.of("phase", "started"));
    String modelId = null;
    String version = null;
    try {
      // 从别名列表中解析模型；当前实现：遍历 alias 列表查找匹配项
      // 若未来引入专门的查询接口可以优化为 O(1)。
      List<Map<String, Object>> aliases = modelAliasService.listAliases();
      for (Map<String, Object> m : aliases) {
        Object a = m.get("alias");
        if (a instanceof String s && s.equals(plan.alias)) {
          Object mid = m.get("model_id");
          Object ver = m.get("version");
          if (mid instanceof String ms && !ms.isEmpty()) {
            modelId = ms;
            if (ver instanceof String vs && !vs.isEmpty()) {
              version = vs;
            }
          }
          break;
        }
      }
      if (modelId == null || modelId.isEmpty()) {
        plan.lock.lock();
        try {
          plan.error = "alias not found: " + plan.alias;
          plan.done = true;
        } finally {
          plan.lock.unlock();
        }
        emit(plan, "error", Map.of("msg", plan.error));
        return;
      }
      plan.lock.lock();
      try {
        plan.running = true;
      } finally {
        plan.lock.unlock();
      }
      int i = 0;
      while (i < plan.targets.size()) {
        int end = Math.min(plan.targets.size(), i + plan.batchSize);
        for (int j = i; j < end; ++j) {
          GrayTarget t = plan.targets.get(j);
          Map<String, Object> options = new HashMap<>();
          Map<String, Object> opt = new HashMap<>();
          opt.put("triton_model", modelId);
          if (version != null && !version.isEmpty()) {
            opt.put("triton_model_version", version);
          }
          options.put("options", opt);
          videoAnalyzerClient.setEngine(options);
          videoAnalyzerClient.hotSwapModel(t.pipeline, t.node, "__triton__");
          plan.lock.lock();
          try {
            plan.applied++;
          } finally {
            plan.lock.unlock();
          }
          emit(
              plan,
              "applied",
              Map.of("pipeline", t.pipeline, "node", t.node, "applied", plan.applied));
        }
        i = end;
        if (i < plan.targets.size() && plan.intervalMs > 0) {
          emit(
              plan,
              "state",
              Map.of(
                  "phase",
                  "waiting",
                  "remaining",
                  plan.targets.size() - i));
          try {
            Thread.sleep(plan.intervalMs);
          } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            break;
          }
        }
      }
      plan.lock.lock();
      try {
        plan.running = false;
        plan.done = true;
      } finally {
        plan.lock.unlock();
      }
      emit(plan, "done", Map.of("applied", plan.applied));
    } catch (Exception ex) {
      plan.lock.lock();
      try {
        plan.error = ex.getMessage() != null ? ex.getMessage() : "unknown";
        plan.running = false;
        plan.done = true;
      } finally {
        plan.lock.unlock();
      }
      emit(plan, "error", Map.of("msg", plan.error));
    }
  }

  private void emit(GrayPlan plan, String kind, Map<String, Object> data) {
    Map<String, Object> wrapper = new HashMap<>();
    wrapper.put("kind", kind);
    wrapper.put("data", data);
    wrapper.put("ts", Instant.now().toEpochMilli());
    String json;
    try {
      json = new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(wrapper);
    } catch (Exception ex) {
      return;
    }
    plan.lock.lock();
    try {
      plan.events.add(json);
    } finally {
      plan.lock.unlock();
    }
  }

  private String stringOrDefault(Object v, String def) {
    if (v instanceof String s && !s.isEmpty()) {
      return s;
    }
    return def;
  }

  private int intOrDefault(Object v, int def) {
    if (v instanceof Number n) {
      return n.intValue();
    }
    return def;
  }
}
