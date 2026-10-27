export const documents=[
{id:'ocean',title:'Ocean tides',text:'Ocean tides rise and fall because of the gravitational pull of the Moon and the Sun. Coastal tide tables predict high and low water.'},
{id:'coral',title:'Coral reefs',text:'Coral bleaching happens when warm seawater stresses corals and they expel their symbiotic algae. Reducing ocean warming helps protect reefs.'},
{id:'battery',title:'Battery care',text:'Lithium ion batteries age faster in heat. Avoid leaving a laptop in a hot car and use a moderate charge limit for long term storage.'},
{id:'bread',title:'Bread fermentation',text:'Yeast fermentation produces carbon dioxide that makes bread dough rise. Cool fermentation takes longer and develops flavor.'},
{id:'database',title:'Hybrid retrieval',text:'Hybrid search combines full text keyword matching with semantic vector similarity. Reciprocal rank fusion merges ranked candidate lists on the database server.'},
{id:'gpu',title:'Browser inference',text:'WebGPU accelerates neural network inference in a web browser. WebAssembly provides a CPU fallback when a compatible GPU adapter is unavailable.'},
{id:'quant',title:'Model quantization',text:'INT8 quantization stores model weights using eight bit integers, reducing download size compared to float32 weights. Retrieval quality should be measured after quantization.'},
{id:'sleep',title:'Sleep habits',text:'A consistent bedtime and a dark quiet bedroom support regular sleep. Bright screens and late caffeine can make falling asleep difficult.'},
{id:'hike',title:'Hiking preparation',text:'Before hiking check the weather, carry drinking water and a map, and tell someone your planned route and return time.'},
{id:'index',title:'Index maintenance',text:'After incremental document ingestion, refresh the full text and vector indexes so new knowledge becomes available to retrieval.'},
{id:'privacy',title:'Local embeddings',text:'Generating embeddings locally keeps model inference in the browser. Document text and vectors are still sent to the configured database for storage and search.'},
{id:'plants',title:'Plant watering',text:'Check soil moisture before watering houseplants. Overwatering reduces oxygen around roots and can cause root rot.'}
];
export const queries=[{text:'Why does the sea level rise twice a day?',relevant:['ocean']},{text:'How does warming water harm reefs?',relevant:['coral']},{text:'How can I prevent laptop battery aging?',relevant:['battery']},{text:'What causes dough to expand?',relevant:['bread']},{text:'Combining semantic and keyword search',relevant:['database']},{text:'How can a browser run a model without a GPU?',relevant:['gpu']},{text:'Reduce neural network weight download size',relevant:['quant']},{text:'How do new documents become searchable?',relevant:['index']}];
