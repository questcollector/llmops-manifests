output "gcsCloudSqlPrivateIP" {
  value = google_sql_database_instance.kubeflow_db.private_ip_address
}
