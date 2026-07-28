# Knowledge Corpus Retrieval Report

- Release: `bazi-theory-classics-structured-v2`
- Manifest SHA256: `313f9a968a7d6ec930a086a5426c3a5b01ca7d667efb1614a9984fbd7ba315d4`
- Gold SHA256: `33093ddef33c6b40a36788f806205e6d9a088d0200c22419c339c1d9516a6e28`
- Base commit: `f8701aa0a417648c38d8ab57743ffd2f929bf85d`
- Candidate tree SHA256: `e47d103834a54ed7026c0d369aea6aaaca0c1bf98cad59786b34a2839e5392d4` (619 files)
- Knowledge config SHA256: `3d423f3137790987467c41f2b20675c6df00ed57506c14bb6b8a4aa8291ea0ba`
- Knowledge snapshot SHA256: `08b7a8b623af54e6aced455bcc226c1afa3c93fb786a71fb6df82c6f86ea0d8d` (9 sources, 402 chunks, 402 current embeddings)
- Embedding config: `d39e826c953842cf`
- Models: `BAAI/bge-small-zh-v1.5` / `BAAI/bge-reranker-base`

| Metric | Value |
| --- | ---: |
| case_count | 24 |
| recall_at_1 | 0.7083 |
| recall_at_3 | 0.9583 |
| recall_at_5 | 1.0000 |
| mrr | 0.8229 |
| expected_source_first_rate | 0.7083 |
| citation_metadata_complete_rate | 1.0000 |
| heading_match_rate | 1.0000 |
| empty_result_count | 0 |
| false_positive_case_count | 0 |
| first_evidence_kind_match_rate | 0.8750 |
| required_text_match_rate | 0.7917 |
| mean_duplicate_source_ratio | 0.3333 |

| Case | Rank | Mode | Vector | Rerank | Citation |
| --- | ---: | --- | --- | --- | --- |
| concept_month_robbery | 1 | hybrid_rerank | available | available | True |
| concept_jianlu_success | 2 | hybrid_rerank | available | available | True |
| concept_yongshen_month | 1 | hybrid_rerank | available | available | True |
| concept_forward_reverse | 1 | hybrid_rerank | available | available | True |
| concept_pattern_success | 1 | hybrid_rerank | available | available | True |
| concept_pattern_failure | 2 | hybrid_rerank | available | available | True |
| concept_rescue | 3 | hybrid_rerank | available | available | True |
| concept_pattern_change | 3 | hybrid_rerank | available | available | True |
| concept_four_good_break | 1 | hybrid_rerank | available | available | True |
| concept_four_bad_form | 1 | hybrid_rerank | available | available | True |
| concept_disease_remedy | 1 | hybrid_rerank | available | available | True |
| concept_four_diseases | 1 | hybrid_rerank | available | available | True |
| concept_four_remedies | 1 | hybrid_rerank | available | available | True |
| concept_day_master | 1 | hybrid_rerank | available | available | True |
| concept_month_command | 2 | hybrid_rerank | available | available | True |
| concept_hurting_officer | 1 | hybrid_rerank | available | available | True |
| concept_food_god | 1 | hybrid_rerank | available | available | True |
| concept_officer | 1 | hybrid_rerank | available | available | True |
| concept_seven_killings | 3 | hybrid_rerank | available | available | True |
| concept_seal | 1 | hybrid_rerank | available | available | True |
| concept_mixed_qi | 4 | hybrid_rerank | available | available | True |
| concept_balance | 1 | hybrid_rerank | available | available | True |
| concept_flow | 1 | hybrid_rerank | available | available | True |
| concept_spring_jia | 1 | hybrid_rerank | available | available | True |
