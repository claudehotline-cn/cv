package com.cv.cp.service.impl;

import com.cv.cp.service.ModelAliasService;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.locks.ReentrantReadWriteLock;
import org.springframework.stereotype.Service;

@Service
public class ModelAliasServiceImpl implements ModelAliasService {

  private static final Path ALIASES_FILE = Path.of("logs", "model_aliases.json");
  private static final Path HISTORY_FILE = Path.of("logs", "model_aliases_history.json");

  private final ObjectMapper objectMapper;
  private final ReentrantReadWriteLock lock = new ReentrantReadWriteLock();
  private Map<String, AliasEntry> aliases;
  private List<HistoryEntry> history;
  private boolean loaded;

  public ModelAliasServiceImpl(ObjectMapper objectMapper) {
    this.objectMapper = objectMapper;
  }

  @Override
  public List<Map<String, Object>> listAliases() {
    lock.readLock().lock();
    try {
      ensureLoaded();
      List<Map<String, Object>> out = new ArrayList<>();
      for (Map.Entry<String, AliasEntry> e : aliases.entrySet()) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("alias", e.getKey());
        m.put("model_id", e.getValue().modelId());
        if (e.getValue().version() != null && !e.getValue().version().isEmpty()) {
          m.put("version", e.getValue().version());
        }
        out.add(m);
      }
      return out;
    } finally {
      lock.readLock().unlock();
    }
  }

  @Override
  public void putAlias(String alias, String modelId, String version) {
    lock.writeLock().lock();
    try {
      ensureLoaded();
      aliases.put(alias, new AliasEntry(modelId, version));
      saveAliases();
    } finally {
      lock.writeLock().unlock();
    }
  }

  @Override
  public void deleteAlias(String alias) {
    lock.writeLock().lock();
    try {
      ensureLoaded();
      if (aliases.remove(alias) != null) {
        saveAliases();
      }
    } finally {
      lock.writeLock().unlock();
    }
  }

  @Override
  public void promote(String alias, String modelId, String version) {
    lock.writeLock().lock();
    try {
      ensureLoaded();
      aliases.put(alias, new AliasEntry(modelId, version));
      saveAliases();
      HistoryEntry ev =
          new HistoryEntry(Instant.now().toEpochMilli(), "promote", alias, modelId, version);
      history.add(ev);
      saveHistory();
    } finally {
      lock.writeLock().unlock();
    }
  }

  @Override
  public void rollback(String alias) {
    lock.writeLock().lock();
    try {
      ensureLoaded();
      // 找上一条映射：从后往前找到该 alias 的第二条记录
      String prevModel = null;
      String prevVersion = null;
      int found = 0;
      for (int i = history.size() - 1; i >= 0; --i) {
        HistoryEntry ev = history.get(i);
        if (!alias.equals(ev.alias())) {
          continue;
        }
        found++;
        if (found == 2) {
          prevModel = ev.modelId();
          prevVersion = ev.version();
          break;
        }
      }
      if (prevModel == null || prevModel.isEmpty()) {
        throw new NotFoundException("no previous mapping");
      }
      aliases.put(alias, new AliasEntry(prevModel, prevVersion));
      saveAliases();
      HistoryEntry ev =
          new HistoryEntry(
              Instant.now().toEpochMilli(), "rollback", alias, prevModel, prevVersion);
      history.add(ev);
      saveHistory();
    } finally {
      lock.writeLock().unlock();
    }
  }

  @Override
  public List<Map<String, Object>> listHistory(String alias) {
    lock.readLock().lock();
    try {
      ensureLoaded();
      List<Map<String, Object>> out = new ArrayList<>();
      for (HistoryEntry ev : history) {
        if (alias != null && !alias.isEmpty() && !alias.equals(ev.alias())) {
          continue;
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("ts", ev.ts());
        m.put("action", ev.action());
        m.put("alias", ev.alias());
        if (ev.modelId() != null && !ev.modelId().isEmpty()) {
          m.put("model_id", ev.modelId());
        }
        if (ev.version() != null && !ev.version().isEmpty()) {
          m.put("version", ev.version());
        }
        out.add(m);
      }
      return out;
    } finally {
      lock.readLock().unlock();
    }
  }

  private void ensureLoaded() {
    if (loaded) {
      return;
    }
    lock.writeLock().lock();
    try {
      if (loaded) {
        return;
      }
      this.aliases = new LinkedHashMap<>();
      this.history = new ArrayList<>();
      loadAliases();
      loadHistory();
      loaded = true;
    } finally {
      lock.writeLock().unlock();
    }
  }

  private void loadAliases() {
    if (!Files.exists(ALIASES_FILE)) {
      return;
    }
    try {
      byte[] bytes = Files.readAllBytes(ALIASES_FILE);
      if (bytes.length == 0) {
        return;
      }
      List<Map<String, Object>> arr =
          objectMapper.readValue(bytes, new TypeReference<List<Map<String, Object>>>() {});
      for (Map<String, Object> m : arr) {
        Object a = m.get("alias");
        Object mid = m.get("model_id");
        Object ver = m.get("version");
        if (!(a instanceof String) || !(mid instanceof String)) {
          continue;
        }
        String alias = (String) a;
        String modelId = (String) mid;
        String version = ver instanceof String ? (String) ver : null;
        if (!alias.isEmpty() && !modelId.isEmpty()) {
          aliases.put(alias, new AliasEntry(modelId, version));
        }
      }
    } catch (IOException ex) {
      // ignore and keep empty
    }
  }

  private void loadHistory() {
    if (!Files.exists(HISTORY_FILE)) {
      return;
    }
    try {
      byte[] bytes = Files.readAllBytes(HISTORY_FILE);
      if (bytes.length == 0) {
        return;
      }
      List<Map<String, Object>> arr =
          objectMapper.readValue(bytes, new TypeReference<List<Map<String, Object>>>() {});
      for (Map<String, Object> m : arr) {
        Object ts = m.get("ts");
        Object action = m.get("action");
        Object alias = m.get("alias");
        Object modelId = m.get("model_id");
        Object version = m.get("version");
        long tsVal;
        if (ts instanceof Number) {
          tsVal = ((Number) ts).longValue();
        } else {
          continue;
        }
        if (!(action instanceof String) || !(alias instanceof String)) {
          continue;
        }
        String act = (String) action;
        String al = (String) alias;
        String mid = modelId instanceof String ? (String) modelId : null;
        String ver = version instanceof String ? (String) version : null;
        history.add(new HistoryEntry(tsVal, act, al, mid, ver));
      }
    } catch (IOException ex) {
      // ignore and keep empty
    }
  }

  private void saveAliases() {
    try {
      Files.createDirectories(ALIASES_FILE.getParent());
      List<Map<String, Object>> arr = new ArrayList<>();
      for (Map.Entry<String, AliasEntry> e : aliases.entrySet()) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("alias", e.getKey());
        m.put("model_id", e.getValue().modelId());
        if (e.getValue().version() != null && !e.getValue().version().isEmpty()) {
          m.put("version", e.getValue().version());
        }
        arr.add(m);
      }
      byte[] out = objectMapper.writeValueAsBytes(arr);
      Files.write(ALIASES_FILE, out);
    } catch (IOException ex) {
      // ignore persist failure
    }
  }

  private void saveHistory() {
    try {
      Files.createDirectories(HISTORY_FILE.getParent());
      List<Map<String, Object>> arr = new ArrayList<>();
      for (HistoryEntry ev : history) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("ts", ev.ts());
        m.put("action", ev.action());
        m.put("alias", ev.alias());
        if (ev.modelId() != null && !ev.modelId().isEmpty()) {
          m.put("model_id", ev.modelId());
        }
        if (ev.version() != null && !ev.version().isEmpty()) {
          m.put("version", ev.version());
        }
        arr.add(m);
      }
      byte[] out = objectMapper.writeValueAsBytes(arr);
      Files.write(HISTORY_FILE, out);
    } catch (IOException ex) {
      // ignore persist failure
    }
  }

  private record AliasEntry(String modelId, String version) {}

  private record HistoryEntry(long ts, String action, String alias, String modelId, String version) {}

  public static class NotFoundException extends RuntimeException {
    public NotFoundException(String msg) {
      super(msg);
    }
  }
}

