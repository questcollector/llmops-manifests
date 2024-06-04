variable "project_id" {
  type        = string
  description = "google cloud project id"
}
variable "region" {
  type        = string
  description = "The region for provisioning resources"
}
variable "domain" {
  type        = string
  description = "domain address for kubeflow/mlflow/inferenceservice application"
}
variable "gke_node_count" {
  type        = number
  description = "node count by zone"
  default     = 1
}
variable "gke_node_machine_type" {
  type        = string
  description = "machine type of nodes"
  default     = "e2-standard-8"
}
