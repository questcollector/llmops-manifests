output "rds_endpoint" {
  description = "rds endpoint"
  value       = aws_db_instance.mysql.address
}

output "rds_port" {
  description = "rds port"
  value       = aws_db_instance.mysql.port
}

output "rds_username" {
  description = "rds username"
  value       = aws_db_instance.mysql.username
}

output "rds_password" {
  description = "rds password"
  sensitive   = true
  value       = aws_db_instance.mysql.password
}

output "s3_bucket" {
  description = "s3 bucket name"
  value       = aws_s3_bucket.kubeflow.id
}

output "region" {
  description = "AWS region"
  value       = var.region
}

output "cluster_name" {
  description = "Kubernetes Cluster Name"
  value       = module.eks.cluster_name
}

output "access_key_id" {
  value     = aws_iam_access_key.temp_key.id
  sensitive = true
}

output "secret_access_key" {
  value     = aws_iam_access_key.temp_key.secret
  sensitive = true
}