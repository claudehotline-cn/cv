## 引言：Transformer的诞生背景与行业影响

序列处理长期受限于RNN的梯度消失问题与LSTM的顺序依赖瓶颈。1990年代Elman网络和1995年LSTM虽逐步优化，但模型仍需逐token处理，导致长序列信息丢失（如380M参数LSTM翻译模型在长输入时性能骤降）。2014年seq2seq架构引入注意力机制，但未解决并行化缺陷。2017年，Google团队在《Attention Is All You Need》中提出Transformer，摒弃循环单元，采用多头注意力机制实现token并行处理，计算复杂度O(n²)却显著提升训练效率（比LSTM快2-3倍）。

**核心突破**：
- 直接建模长距离依赖，解决vanishing-gradient问题
- 无顺序依赖：处理1000 token仅需1步（LSTM需1000步）

**行业影响**：
- **NLP革命**：BERT在GLUE基准超人类水平（80.5% vs 80.3%），GPT-3达175B参数
- **跨领域爆发**：ViT图像分类83.1%（超越CNN 81.3%）、AlphaFold 2蛋白质结构预测92.4%
- **范式转变**：2023年85%的AI模型基于Transformer，推动预训练+微调范式，NLP任务准确率平均提升15-25%。