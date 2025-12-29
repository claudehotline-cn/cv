## Variants

Transformer 架构催生了多个关键变体，显著扩展了其在自然语言处理（NLP）领域的应用范围。这些变体针对不同任务优化了原始架构，推动了预训练模型范式的演进。本章节聚焦于最核心的变体：BERT 和 GPT，它们基于 Transformer 架构的创新设计，分别服务于理解与生成任务。

### BERT (Bidirectional Encoder Representations from Transformers)

BERT 是 Google 研究团队于 2018 年开发的预训练模型，作为 Transformer 架构在 NLP 领域的关键应用。其核心创新在于双向编码器设计，允许模型同时利用输入序列中每个 token 的左右上下文信息（即从左到右和从右到左），从而克服传统序列建模方法（如 RNN 和 LSTM）的局限性。例如，早期 seq2seq 模型因固定大小的输出向量导致长文本信息丢失，而 BERT 通过双向机制有效捕获上下文依赖。

BERT 的训练采用两个核心任务：
- **掩码语言建模 (Masked Language Modeling)**：随机掩码输入中约 15% 的 token，并预测被掩码的词，以学习上下文相关的词表示。
- **下一句预测 (Next Sentence Prediction)**：判断两个句子是否连续，增强对句子关系的理解。

这些任务使 BERT 能够生成高质量的上下文表示。其变体（如 BERT-base 和 BERT-large）在多个基准测试中显著提升性能，例如在 SQuAD 问答数据集上超越传统模型。BERT 被广泛应用于下游任务，包括文本分类、问答系统和句子相似度计算，并成为大型语言模型（LLMs）训练的基础。如素材文本所述："Later variations have been widely adopted for training large language models (LLMs) on large (language) datasets." 这一变体源于 Google 研究团队对 Transformer 架构的扩展，旨在改进语言理解任务。

### GPT (Generative Pre-trained Transformers)

GPT 是 Google 研究团队开发的生成式预训练系统，采用解码器-only 架构，专注于文本生成任务。其开发早于正式论文发布（2017 年春季），用于生成虚构内容，如维基百科文章。GPT 的核心特性包括：
- **自回归生成**：通过最大化文本似然来学习语言模型，允许模型动态利用上下文生成连贯文本。
- **并行化优势**：利用 Transformer 的并行化能力，显著减少训练时间，避免了早期 RNN 架构的序列依赖问题。

GPT 的变体（如 GPT-2 和 GPT-3）在多个语言任务上表现优异，例如文本续写和摘要生成。它被广泛用于训练大型语言模型（LLMs），并推动了生成式 AI 的发展。如素材文本所述："Transformer architecture is now used alongside many generative models that contribute to the ongoing AI boom." GPT 的设计源于对序列建模并行化问题的解决，其解码器-only 结构使模型能高效处理生成任务。

### 总结与影响

BERT 和 GPT 作为 Transformer 的主要变体，分别代表了理解与生成任务的范式转变。BERT 通过双向编码器提升了语言理解能力，而 GPT 通过解码器-only 架构优化了文本生成。两者共同推动了 NLP 领域的进展，使模型能够处理更复杂的语言任务，并成为现代大型语言模型（LLMs）的基石。这些变体的广泛应用，如素材文本所述，"Later variations have been widely adopted for training large language models (LLMs) on large (language) datasets"，凸显了 Transformer 架构在 AI 领域的持久影响力。