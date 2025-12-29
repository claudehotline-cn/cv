## 架构详解：自注意力与多头机制

### 自注意力机制的数学原理

自注意力机制（Self-Attention）通过计算序列中每个元素与其他元素的相关性，实现上下文感知的特征表示。给定输入序列 \( X = [x_1, x_2, \dots, x_n] \)，其中 \( x_i \in \mathbb{R}^d \)，首先通过线性变换生成查询（Query）、键（Key）和值（Value）矩阵：

\[
Q = XW_Q, \quad K = XW_K, \quad V = XW_V
\]

其中 \( W_Q, W_K, W_V \in \mathbb{R}^{d \times d_k} \) 为可学习参数矩阵。注意力分数通过点积计算并缩放：

\[
\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V
\]

该公式通过缩放因子 \( \frac{1}{\sqrt{d_k}} \) 防止梯度消失，softmax函数确保注意力权重和为1，最终输出为加权求和的值向量。此过程使模型能够动态调整不同位置词的权重，实现对上下文的自适应建模，有效解决传统RNN的长距离依赖问题。

### 多头注意力机制的设计与优势

多头注意力（Multi-Head Attention）通过并行计算多个注意力头，捕捉不同子空间的依赖关系：

\[
\text{MultiHead}(Q, K, V) = \text{Concat}(\text{head}_1, \dots, \text{head}_h)W_O
\]

其中每个头计算为：

\[
\text{head}_i = \text{Attention}(QW_i^Q, KW_i^K, VW_i^V)
\]

\( W_i^Q, W_i^K, W_i^V \in \mathbb{R}^{d \times d_k} \) 为各头的投影矩阵，\( W_O \in \mathbb{R}^{hd_k \times d} \) 为输出投影矩阵。多头机制使模型能够同时关注输入序列的不同特征维度，例如局部语法结构和全局语义关系，显著提升表示能力。与传统模型相比，其并行化特性将训练效率提升3-5倍（如100M参数Transformer模型对比380M seq2seq模型），同时通过多头设计有效缓解了长距离依赖问题。

### 事实修正与历史背景

需明确：2016年提出的decomposable attention模型（Parikh et al.）虽使用了注意力机制，但并非自注意力机制。该模型将注意力应用于前馈网络，用于文本蕴含任务，其核心是通过注意力机制对输入进行分块处理，而非序列内部的自注意力计算。自注意力机制的正式提出应归功于2017年Transformer论文，该工作首次将自注意力作为核心组件，实现了序列建模的范式转变。值得注意的是，decomposable attention的作者Jakob Uszkoreit曾推测"attention without recurrence would be sufficient for language translation"，这一思想直接启发了Transformer的提出。

### 与传统模型的对比

与RNN/LSTM相比，自注意力机制完全摒弃了循环结构，实现并行计算，将时间复杂度从 \( O(n) \) 降至 \( O(n^2) \)，但通过GPU并行化大幅提升了训练效率。例如，Transformer在机器翻译任务中，100M参数模型的训练速度比传统seq2seq模型快3-5倍。此外，自注意力机制有效解决了RNN的梯度消失问题，使模型能够精确捕捉长序列中的语义关联，避免了固定大小向量导致的信息丢失。多头注意力通过独立头设计，使模型能够同时关注输入序列的不同部分，显著提升处理复杂依赖关系的能力。

### 位置编码的协同作用

由于Transformer缺乏RNN的顺序处理特性，位置编码（Positional Encoding）通过正弦/余弦函数将位置信息注入词嵌入：

\[
PE_{(pos, 2i)} = \sin\left(\frac{pos}{10000^{2i/d}}\right), \quad PE_{(pos, 2i+1)} = \cos\left(\frac{pos}{10000^{2i/d}}\right)
\]

其中 \( pos \) 为位置索引，\( i \) 为维度索引。位置编码与词嵌入相加，使模型能够区分不同位置的词，同时保持对位置关系的平移不变性，与自注意力机制协同工作，有效处理长距离依赖。这一设计使Transformer在保持并行化优势的同时，完整保留了序列的顺序信息。