import numpy as np
import triton_python_backend_utils as pb_utils


def iou(box1, box2):
    # boxes: [x1,y1,x2,y2]
    inter_x1 = max(box1[0], box2[0])
    inter_y1 = max(box1[1], box2[1])
    inter_x2 = min(box1[2], box2[2])
    inter_y2 = min(box1[3], box2[3])
    iw = max(0.0, inter_x2 - inter_x1)
    ih = max(0.0, inter_y2 - inter_y1)
    inter = iw * ih
    a1 = max(0.0, (box1[2] - box1[0])) * max(0.0, (box1[3] - box1[1]))
    a2 = max(0.0, (box2[2] - box2[0])) * max(0.0, (box2[3] - box2[1]))
    union = a1 + a2 - inter + 1e-6
    return inter / union


class TritonPythonModel:
    def initialize(self, args):
        self.conf = 0.25
        self.iou_thr = 0.45
        try:
            cfg = pb_utils.get_model_config()
            params = cfg.get('parameters', {}) or {}
            c = params.get('conf', {}).get('string_value', '0.25')
            i = params.get('iou', {}).get('string_value', '0.45')
            self.conf = float(c)
            self.iou_thr = float(i)
        except Exception:
            pass

    def execute(self, requests):
        responses = []
        for req in requests:
            inp = pb_utils.get_input_tensor_by_name(req, 'raw')
            raw = inp.as_numpy()
            if raw.ndim == 3:
                raw = raw[0]
            # Expect per-row: [x,y,w,h, conf, cls_logits...], common for YOLO variants
            if raw.shape[1] >= 6:
                xywh = raw[:, :4]
                conf = raw[:, 4]
                cls_scores = raw[:, 5:]
                cls_ids = np.argmax(cls_scores, axis=1)
                scores = conf * np.max(cls_scores, axis=1)
            else:
                # Fallback: treat 5 cols: x,y,w,h,score and cls=0
                xywh = raw[:, :4]
                scores = raw[:, 4]
                cls_ids = np.zeros_like(scores, dtype=np.int32)

            # Filter by confidence
            keep = scores >= self.conf
            xywh = xywh[keep]
            scores_f = scores[keep]
            cls_ids_f = cls_ids[keep]

            # Convert to x1y1x2y2
            x1 = xywh[:, 0] - xywh[:, 2] / 2.0
            y1 = xywh[:, 1] - xywh[:, 3] / 2.0
            x2 = xywh[:, 0] + xywh[:, 2] / 2.0
            y2 = xywh[:, 1] + xywh[:, 3] / 2.0
            boxes = np.stack([x1, y1, x2, y2], axis=1)

            # NMS (greedy)
            order = np.argsort(-scores_f)
            selected = []
            while order.size > 0:
                i = order[0]
                selected.append(i)
                if order.size == 1:
                    break
                rest = order[1:]
                ious = np.array([iou(boxes[i], boxes[j]) for j in rest])
                rest = rest[ious < self.iou_thr]
                order = rest

            dets = []
            for i in selected:
                dets.append([boxes[i, 0], boxes[i, 1], boxes[i, 2], boxes[i, 3], scores_f[i], float(cls_ids_f[i]), 0.0])
            dets = np.array(dets, dtype=np.float32) if dets else np.zeros((0, 7), dtype=np.float32)
            out = pb_utils.Tensor('dets', dets)
            responses.append(pb_utils.InferenceResponse(output_tensors=[out]))
        return responses

