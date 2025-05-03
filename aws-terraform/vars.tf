variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "eks cpu instance type"
  type        = string
  default     = "t3.xlarge"
}

variable "mysql_port" {
  description = "mysql port"
  type        = string
  default     = "43256"
}

variable "mysql_instance_type" {
  description = "mysql instance type"
  type        = string
  default     = "db.t3.medium"
}

variable "mysql_username" {
  description = "mysql username"
  type        = string
  default     = "admin"
}



