import {pipeline, env} from '@huggingface/transformers';
import {MODEL_ID, MODEL_REVISION} from './model.js';
env.allowLocalModels = false;
env.backends.onnx.wasm.numThreads = 1;
let extractor, activeKey, actualDevice, queue = Promise.resolve();

async function run({id, texts, dtype = 'q8', device = 'webgpu'}) {
  try {
    const key = dtype + device;
    let loadMs = 0;
    if (key !== activeKey) {
      if (extractor) await extractor.dispose();
      extractor = null;
      activeKey = null;
      actualDevice = device;
      const loadStart = performance.now();
      if (device === 'webgpu' && (!navigator.gpu || !await navigator.gpu.requestAdapter())) {
        actualDevice = 'wasm';
        self.postMessage({id, fallback:'浏览器未提供可用 GPU adapter'});
      }
      try {
        extractor = await pipeline('feature-extraction', MODEL_ID, {
          revision: MODEL_REVISION, dtype, device: actualDevice,
          progress_callback: progress => self.postMessage({id, progress})
        });
      } catch (error) {
        if (actualDevice !== 'webgpu') throw error;
        self.postMessage({id, retryWasm:true, fallback:String(error.message)});
        return;
      }
      loadMs = performance.now() - loadStart;
      activeKey = key;
    }
    const start = performance.now();
    const output = await extractor(texts, {pooling:'mean', normalize:true});
    self.postMessage({id, embeddings:output.tolist(), ms:performance.now()-start,
      loadMs, device:actualDevice, dtype, revision:MODEL_REVISION});
  } catch (error) {
    self.postMessage({id, error:error.message});
  }
}

// 排队处理模型切换，避免导入与查询同时更换或释放正在使用的模型。
self.onmessage = ({data}) => { queue = queue.then(() => run(data)); };
