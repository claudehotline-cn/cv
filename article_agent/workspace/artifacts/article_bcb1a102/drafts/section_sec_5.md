## 变体模型演进：BERT、GPT与T5的技术突破

Transformer架构于2017年《Attention Is All You Need》提出，以多头注意力机制实现并行化处理，取代RNN的顺序计算，训练效率提升3-5倍。基于此，BERT、GPT与T5三大变体模型引领NLP技术突破。

- **BERT**：采用双向编码器架构，通过掩码语言建模（MLM）预训练，随机遮盖输入15% token预测其内容，能同时利用token左右上下文（如“[MASK] is a good [MASK]”预测“apple”和“fruit”）。在GLUE基准测试中，BERT-base平均性能提升7.7%，推动NLP从特征工程转向预训练+微调范式。下游任务仅需1-2个epoch微调（如添加分类层），大幅降低数据需求。

- **GPT系列**：基于Transformer解码器，单向自回归生成文本。GPT-1（2018）通过语言建模预训练；GPT-2（2019）扩大至1.5B参数，支持提示工程（如“Translate English to French: Hello”）；GPT-3（2020）拥有175B参数和45TB训练数据，实现零样本能力，无需微调即可完成新任务（如“Write a poem about AI”），生成准确率超传统模型20%。

- **T5**：作为融合模型，统一文本到文本框架。将各类任务（如分类、翻译）转化为“translate: [input] to [output]”（如问答转为“translate: [question] to [answer]”），结合BERT的双向理解与GPT的生成优势，提升任务泛化性。例如，分类任务无需额外架构，直接复用预训练表示。

此演进标志着NLP范式从任务特定模型转向通用预训练+微调，计算效率显著提升（380M LSTM训练需数周，同等规模Transformer仅需数天），企业仅需微调即可部署应用，大幅降低技术门槛。BERT与GPT的互补性催生T5，推动开源生态（如Hugging Face）普及，奠定现代大模型基础。