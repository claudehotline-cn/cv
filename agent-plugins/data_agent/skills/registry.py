"""
Skills Registry for Analyst Agent.
Stores the prompts and examples for different analysis skills.
"""

SKILLS_REGISTRY = {
    "general": {
        "name": "General Data Processing",
        "instruction": """
[Step 3.1] 数据清洗
- 类型转换
- 缺失值处理
- 排序

[Step 3.2] 核心变换
场景 A (绘图准备 - 关键！): 
- 如果任务是**画多系列图表**（如"各城市销售趋势"），**必须使用 `pivot_table` 将数据转换为宽表**！
  - Index = X轴 (如 month)
  - Columns = 系列名 (如 city_name)
  - Values = 数值 (如 sales)
  - **最后必须 reset_index()** 保持扁平化，或者 Visualizer 能处理 Index 也可以。
  - **示例**：`df = df.pivot_table(index='month', columns='city', values='sales', aggfunc='sum').reset_index()`

场景 B (聚合计算): groupby sum/mean/count
""",
        "examples": """
# 示例：准备多系列图表数据 (Pivot)
# df = load_dataframe('sql_result')
# pivot_df = df.pivot_table(index='month', columns='city', values='amount', aggfunc='sum')
# pivot_df = pivot_df.reset_index() # 让 month 变回普通列
# result = pivot_df
"""
    },
    "statistics": {
        "name": "Statistical Analysis (scipy/statsmodels)",
        "instruction": """
**【核心能力】**
1. **描述性统计**：均值、标准差、分位数、偏度、峰度
2. **假设检验**：t检验、卡方检验、ANOVA、Mann-Whitney U
3. **相关性分析**：Pearson、Spearman
4. **回归分析**：线性回归

**必须输出**：
- 统计量值（t-stat, F-stat, chi2）
- p-value
- 效应量
- 自然语言解释结论
        """,
        "examples": """
# 示例：T检验
# from scipy import stats
# group_a = df[df['group']=='A']['value']
# group_b = df[df['group']=='B']['value']
# t_stat, p_val = stats.ttest_ind(group_a, group_b)
# print(f"T-test result: t={t_stat}, p={p_val}")
"""
    },
    "ml": {
        "name": "Machine Learning (scikit-learn)",
        "instruction": """
**【核心能力】**
1. **数据预处理**：StandardScaler, LabelEncoder, SimpleImputer
2. **特征工程**：PCA, SelectKBest
3. **聚类分析**：K-Means, DBSCAN
4. **异常检测**：Isolation Forest
5. **分类/回归**（用于预测）

**【禁止事项】**
- ❌ 禁止保存模型到文件
- ❌ 禁止使用 pickle
        """,
        "examples": """
# 示例：K-Means 聚类
# from sklearn.cluster import KMeans
# from sklearn.preprocessing import StandardScaler
# X = df[['col1', 'col2']]
# X_scaled = StandardScaler().fit_transform(X)
# kmeans = KMeans(n_clusters=3).fit(X_scaled)
# df['cluster'] = kmeans.labels_
# result = df
"""
    }
}
