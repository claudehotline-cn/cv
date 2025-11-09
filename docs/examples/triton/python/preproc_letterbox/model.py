import numpy as np
import triton_python_backend_utils as pb_utils


class TritonPythonModel:
    def initialize(self, args):
        self.normalize = True
        try:
            cfg = pb_utils.get_model_config()
            params = cfg.get('parameters', {}) or {}
            v = params.get('normalize', {}).get('string_value', 'true').lower()
            self.normalize = v in ('1', 'true', 'yes', 'on')
        except Exception:
            pass

    def execute(self, requests):
        responses = []
        for req in requests:
            inp = pb_utils.get_input_tensor_by_name(req, 'rgb8')
            arr = inp.as_numpy()
            # Expect shape [N?, 3, H, W] or [3, H, W]; coerce to 3xHxW
            if arr.ndim == 4:
                arr = arr[0]
            # Convert to float32 + normalize to [0,1]
            out = arr.astype(np.float32)
            if self.normalize:
                out /= 255.0
            out_tensor = pb_utils.Tensor('images', out)
            responses.append(pb_utils.InferenceResponse(output_tensors=[out_tensor]))
        return responses

