## 引言：Transformer的诞生与影响

Transformer架构通过多头自注意力机制（Multi-Head Self-Attention）革新了序列建模领域。其核心公式为：  
$$ \text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V $$  
其中，$ Q, K, V $ 分别为查询、键、值矩阵，$ d_k $ 为键向量维度。Softmax归一化确保注意力权重总和为1，增强模型对关键信息的聚焦能力。

### 技术演进与对比
| 指标         | RNN/LSTM       | Transformer    |
|--------------|----------------|----------------|
| 计算并行性   | 顺序处理（低） | 全并行（高）   |
| 长序列建模   | 梯度消失（差） | 注意力机制（优）|
| 可解释性     | 低（黑箱）     | 中（注意力权重可视化）|
| 训练效率     | $ O(n) $      | $ O(n^2) $（优化后线性）|

### 应用突破
- **NLP**：BERT（2018）在GLUE基准测试中超越RNN模型，准确率提升15%  
- **CV**：ViT（2020）在ImageNet分类任务中达到84.2% Top-1准确率  
- **效率优化**：Linformer（2020）通过线性投影将复杂度降至$ O(n) $，训练时间减少40%

### 历史意义
Google团队在2017年《Attention Is All You Need》中提出Transformer，解决了RNN的顺序处理瓶颈。其并行计算能力使训练时间从RNN的数天缩短至数小时，推动了GPT、T5等大模型的诞生，成为AI领域里程碑式创新。