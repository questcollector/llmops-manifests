provider "google" {
  project = var.project_id
  region  = var.region
}

# ### tfstate를 GCS bucket에 저장하고 싶은 경우 주석 해제
# terraform {
#   backend "gcs" {
#  	  ### terraform state가 저장될 google cloud storage bucket 이름 지정
#     bucket = "<<TF_STATE_BUCKET>>"
#     prefix = "terraform/state"
#   }
# }
