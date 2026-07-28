# Knowledge Corpus Retrieval Report

- Release: `bazi-theory-sandbox-local-20260728`
- Manifest SHA256: `runtime-namespace`
- Gold SHA256: `f69f6ab21c0d976e1530173f48343900f8833b8bda405e471f6822db88e9b64c`
- Base commit: `f8701aa0a417648c38d8ab57743ffd2f929bf85d`
- Candidate tree SHA256: `9ac56801b541d90293bcbde45a21d0a465a8ec351b177be3d36209c07790ff28` (602 files)
- Knowledge config SHA256: `3d423f3137790987467c41f2b20675c6df00ed57506c14bb6b8a4aa8291ea0ba`
- Knowledge snapshot SHA256: `b0e614d444d6b20b9c010f72e1d40c7bf5bc867bd9bffb35c1d47115e630ac14` (15 sources, 792 chunks, 792 current embeddings)
- Embedding config: `d39e826c953842cf`
- Models: `BAAI/bge-small-zh-v1.5` / `BAAI/bge-reranker-base`

| Metric | Value |
| --- | ---: |
| case_count | 23 |
| recall_at_1 | 0.9130 |
| recall_at_3 | 1.0000 |
| recall_at_5 | 1.0000 |
| mrr | 0.9565 |
| expected_source_first_rate | 0.9130 |
| citation_metadata_complete_rate | 1.0000 |
| heading_match_rate | 1.0000 |
| empty_result_count | 0 |
| false_positive_case_count | 1 |

| Case | Rank | Mode | Vector | Rerank | Citation |
| --- | ---: | --- | --- | --- | --- |
| ziping_useful_god | 1 | hybrid_rerank | available | available | True |
| xia_zhongqi_catalog | 1 | hybrid_rerank | available | available | True |
| hao_jinyang_brick_kiln | 1 | hybrid_rerank | available | available | True |
| zhongyuan_direct_four_pillars | 1 | hybrid_rerank | available | available | True |
| renfuhong_tomb_storage | 1 | hybrid_rerank | available | available | True |
| renfuhong_2017_notes | 1 | hybrid_rerank | available | available | True |
| renfuhong_practice_case | 1 | hybrid_rerank | available | available | True |
| marriage_disaster | 1 | hybrid_rerank | available | available | True |
| hour_pillar_marriage | 1 | hybrid_rerank | available | available | True |
| prison_mourning | 1 | hybrid_rerank | available | available | True |
| peng_kangmin_preface | 1 | hybrid_rerank | available | available | True |
| yang_qingjuan_stems | 1 | hybrid_rerank | available | available | True |
| duan_jianye_system | 1 | hybrid_rerank | available | available | True |
| xing_xiufen_parents | 1 | hybrid_rerank | available | available | True |
| abandon_office_use_food | 1 | hybrid_rerank | available | available | True |
| semantic_useful_god_month | 1 | hybrid_rerank | available | available | True |
| semantic_direct_reading | 1 | hybrid_rerank | available | available | True |
| semantic_tomb_storage | 2 | hybrid_rerank | available | available | True |
| semantic_prison_release | 1 | hybrid_rerank | available | available | True |
| semantic_parent_timing | 1 | hybrid_rerank | available | available | True |
| semantic_stem_colors | 2 | hybrid_rerank | available | available | True |
| semantic_guest_host_work | 1 | hybrid_rerank | available | available | True |
| semantic_abandon_office | 1 | hybrid_rerank | available | available | True |
# Namespace Corpus Profile

- Sources: `15`
- Chunks: `792`
- Indexed chunk characters: `683450`
- Largest source chunk share: `0.356061`
- OCR unreviewed: `3` sources / `429` chunks
- Exact duplicate chunk pairs: `0`
- Cross-source near-duplicate pairs: `0` at threshold `0.9`

| Source | Chunks | Indexed chars | Extraction |
| --- | ---: | ---: | --- |
| ksrc_localtest_blind_yang_qingjuan_244 | 282 | 242461 | ocr_unreviewed |
| ksrc_localtest_ziping_benyi_full | 98 | 82674 | word_text_extracted |
| ksrc_localtest_blind_duan_jianye_2016 | 94 | 72825 | ocr_unreviewed |
| ksrc_localtest_blind_xia_zhongqi | 73 | 67706 | word_text_extracted |
| ksrc_localtest_blind_peng_kangmin | 67 | 57701 | word_text_extracted |
| ksrc_localtest_blind_renfuhong_2017 | 53 | 45371 | ocr_unreviewed |
| ksrc_localtest_blind_zhongyuan | 43 | 42508 | word_text_extracted |
| ksrc_localtest_blind_renfuhong_practice | 28 | 27378 | word_text_extracted |
| ksrc_localtest_blind_xing_xiufen | 21 | 15075 | word_text_extracted |
| ksrc_localtest_blind_haojinyang_formulas | 12 | 11758 | word_text_extracted |
| ksrc_localtest_blind_hour_marriage | 8 | 6364 | word_text_extracted |
| ksrc_localtest_blind_prison_mourning | 7 | 5678 | word_text_extracted |
| ksrc_localtest_blind_renfuhong_tombs | 4 | 4130 | pdf_text_extracted |
| ksrc_localtest_blind_abandon_office | 1 | 717 | word_text_extracted |
| ksrc_localtest_blind_marriage | 1 | 1104 | word_text_extracted |
