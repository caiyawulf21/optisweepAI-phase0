# restart_optisweep_service_after_heartbeat_timeout_v1

```mermaid
flowchart TD
  start[restart_optisweep_service_after_heartbeat_timeout_v1]
  start --> confirm_no_rms_alarms[confirm_no_rms_alarms]
  confirm_no_rms_alarms --> confirm_tipper_heartbeat_timeout[confirm_tipper_heartbeat_timeout]
  confirm_tipper_heartbeat_timeout --> set_master_estop_on[set_master_estop_on]
  set_master_estop_on --> restart_service[restart_service]
  restart_service --> validate_heartbeat[validate_heartbeat]
  validate_heartbeat --> confirm_agv_movement[confirm_agv_movement]
  229374[incident_229374] --> start
  229716[incident_229716] --> start
  229777[incident_229777] --> start
  timeline_229374_restart[evidence_timeline_229374_restart] --> start
  timeline_229716_restart[evidence_timeline_229716_restart] --> start
  timeline_229777_restart[evidence_timeline_229777_restart] --> start
```
