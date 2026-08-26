---
title: Machine learning-based analysis of factors associated with clinical pregnancy in vitrified-warmed single euploid embryo
  transfer cycles.
domain: medical-research
tier: 01-Raw
entry_id: medical-research-clinical-pregnancy-rate-machine-learning-based-analysis-of-factors-associated-with-clinical-pregnancy-in-vitrified-warmed-single-euploid-embryo-transfer-cycles
source_url: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=42566879&retmode=xml
source_type: api
source_platform: pubmed
collected_at: 2026 Jul 04
summary: This retrospective cohort study used machine learning to analyze 4300 vitrified-warmed single euploid embryo transfer
  cycles and identified seven key factors influencing clinical pregnancy, including maternal age, AMH, and endometrial thickness.
  Models like XGBoost achieved good predictive performance (AUC up to 0.778), and SHAP analysis provided interpretable insights.
  These findings may improve risk stratification and optimize IVF treatment strategies.
tags:
- Clinical pregnancy rate
- Euploid embryo
- Machine learning
- Vitrified-warmed embryo transfer
quality_tier: 1
relevance_score: 100.0
dedup_status: unique
source_score: 90.0
language: en
user_id: ''
version: 1
previous_version: 0
supersedes: ''
trace_id: c860a295-4074-4a97-ab65-895c3d3a9b30
quality_flags:
  G0-SchemaIntegrity: false
  G1-SourceAuthority: false
  G1-TosCompliance: false
  G2-Dedup: false
  G3-RelevanceScoring: false
tos_compliant: true
tos_classification: open
---

## Original Content
RESEARCH QUESTION: Which factors influence clinical pregnancy outcomes in vitrified-warmed single euploid embryo transfer cycles using machine learning models?
DESIGN: This retrospective cohort study included 4300 vitrified-warmed single euploid embryo transfer cycles derived exclusively from intracytoplasmic sperm injection or intracytoplasmic morphologically selected sperm injection performed at the Assisted Reproductive Technology and Reproductive Genetics Centre of Sisli Memorial Hospital, Istanbul, Turkey between October 2011 and February 2023. Twenty-six clinical, demographic and embryological variables were analysed using multiple machine learning algorithms, namely Adaptive Boosting (AdaBoost), Random Forest, Extreme Gradient Boosting (XGBoost), Light Gradient Boosting Machine, and Extremely Randomized Trees. Model performance was evaluated using five-fold cross-validation, F1-score and area under the receiver operating characteristic curve (AUC). SHapley Additive exPlanations were used to interpret model outputs.
RESULTS: Seven clinically relevant factors influencing clinical pregnancy were identified: number of previous cycles, anti-Müllerian hormone concentration, endometrial thickness, post-warming embryo quality, maternal age, number of vitrified embryos, and endometrial preparation method. Discriminatory performance was mostly comparable across models, with AUC values ranging from 0.760 (AdaBoost) to 0.778 (XGBoost). Calibration analysis demonstrated that Random Forest and LGBM achieved the best performance in the full feature setting (Brier scores 0.178 and 0.179, respectively), whereas XGBoost showed optimal calibration in the selected feature setting (Brier score 0.201). Pairwise bootstrap analysis (1000 iterations) identified a significant AUC difference between XGBoost and Random Forest (P = 0.048), with no other significant pairwise differences.
CONCLUSIONS: Machine learning models identified key determinants of clinical pregnancy in euploid embryo transfer cycles. These insights may facilitate risk stratification and optimize IVF treatment strategies.

## Summary
This retrospective cohort study used machine learning to analyze 4300 vitrified-warmed single euploid embryo transfer cycles and identified seven key factors influencing clinical pregnancy, including maternal age, AMH, and endometrial thickness. Models like XGBoost achieved good predictive performance (AUC up to 0.778), and SHAP analysis provided interpretable insights. These findings may improve risk stratification and optimize IVF treatment strategies.

## Key Points
- Seven clinically relevant factors: number of previous cycles, anti-Müllerian hormone concentration, endometrial thickness, post-warming embryo quality, maternal age, number of vitrified embryos, and endometrial preparation method.
- AUC values ranged from 0.760 (AdaBoost) to 0.778 (XGBoost), showing comparable discriminative performance across models.
- Random Forest and LGBM had the best calibration in the full feature setting, while XGBoost was best in the selected feature setting.
- Pairwise bootstrap analysis found a significant AUC difference only between XGBoost and Random Forest (P = 0.048).
- Machine learning models can facilitate risk stratification and optimize IVF treatment strategies.


## Entities
- **Machine learning** (technology, relevance=)
- **AdaBoost** (technology, relevance=)
- **Random Forest** (technology, relevance=)
- **XGBoost** (technology, relevance=)
- **Light Gradient Boosting Machine** (technology, relevance=)
- **Extremely Randomized Trees** (technology, relevance=)
- **SHapley Additive exPlanations** (technology, relevance=)
- **Anti-Müllerian hormone** (concept, relevance=)
- **Clinical pregnancy** (concept, relevance=)
- **Vitrified-warmed single euploid embryo transfer** (procedure, relevance=)
- **Sisli Memorial Hospital** (org, relevance=)
- **Intracytoplasmic sperm injection** (procedure, relevance=)
- **Intracytoplasmic morphologically selected sperm injection** (procedure, relevance=)
- **In vitro fertilization** (procedure, relevance=)
