# workflow_symptom_agvs_not_moving_with_suspected_ignition_or_service_issue

```mermaid
flowchart TD
  workflow[workflow_symptom_agvs_not_moving_with_suspected_ignition_or_service_issue]
  agvs_stopped[signal_agvs_stopped] --> workflow
  customer_bridge_gap_identified[signal_customer_bridge_gap_identified] --> workflow
  hmi_question_marks_displayed[signal_hmi_question_marks_displayed] --> workflow
  hospital_tote_removal_hangs[signal_hospital_tote_removal_hangs] --> workflow
  memory_review_did_not_indicate_crash[signal_memory_review_did_not_indicate_crash] --> workflow
  remote_access_unavailable[signal_remote_access_unavailable] --> workflow
  teams_thread_indicates_active_escalation[signal_teams_thread_indicates_active_escalation] --> workflow
  workflow --> proc_228086_01[procedure_proc_228086_01]
  workflow --> proc_228086_02[procedure_proc_228086_02]
  workflow --> proc_228086_03[procedure_proc_228086_03]
  workflow --> proc_228086_04[procedure_proc_228086_04]
  228086[incident_228086] --> workflow
  chunk_228086_01[evidence_chunk_228086_01] --> workflow
  event_228086_01[evidence_event_228086_01] --> workflow
  event_228086_02[evidence_event_228086_02] --> workflow
  case_228086_docx_artifact_01[evidence_case_228086_docx_artifact_01] --> workflow
  chunk_228086_02[evidence_chunk_228086_02] --> workflow
  event_228086_03[evidence_event_228086_03] --> workflow
  case_228086_docx_artifact_01[evidence_case_228086_docx_artifact_01] --> workflow
  chunk_228086_03[evidence_chunk_228086_03] --> workflow
  chunk_228086_04[evidence_chunk_228086_04] --> workflow
  chunk_228086_06[evidence_chunk_228086_06] --> workflow
  event_228086_04[evidence_event_228086_04] --> workflow
  event_228086_05[evidence_event_228086_05] --> workflow
  case_228086_docx_artifact_02[evidence_case_228086_docx_artifact_02] --> workflow
  case_228086_docx_artifact_04[evidence_case_228086_docx_artifact_04] --> workflow
  case_228086_docx_artifact_05[evidence_case_228086_docx_artifact_05] --> workflow
  case_228086_docx_artifact_06[evidence_case_228086_docx_artifact_06] --> workflow
  case_228086_docx_artifact_07[evidence_case_228086_docx_artifact_07] --> workflow
  chunk_228086_05[evidence_chunk_228086_05] --> workflow
  chunk_228086_10[evidence_chunk_228086_10] --> workflow
  chunk_228086_11[evidence_chunk_228086_11] --> workflow
  event_228086_06[evidence_event_228086_06] --> workflow
  event_228086_10[evidence_event_228086_10] --> workflow
  case_228086_docx_artifact_06[evidence_case_228086_docx_artifact_06] --> workflow
  case_228086_docx_artifact_11[evidence_case_228086_docx_artifact_11] --> workflow
  case_228086_docx_artifact_14[evidence_case_228086_docx_artifact_14] --> workflow
  case_228086_docx_artifact_16[evidence_case_228086_docx_artifact_16] --> workflow
  case_228086_docx_artifact_18[evidence_case_228086_docx_artifact_18] --> workflow
  chunk_228086_07[evidence_chunk_228086_07] --> workflow
  chunk_228086_08[evidence_chunk_228086_08] --> workflow
  event_228086_07[evidence_event_228086_07] --> workflow
  event_228086_08[evidence_event_228086_08] --> workflow
  case_228086_docx_artifact_08[evidence_case_228086_docx_artifact_08] --> workflow
  case_228086_docx_artifact_09[evidence_case_228086_docx_artifact_09] --> workflow
  case_228086_docx_artifact_10[evidence_case_228086_docx_artifact_10] --> workflow
```



