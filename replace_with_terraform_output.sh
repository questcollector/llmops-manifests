#!/bin/sh

# 🔄 Terraform output 값을 변수로 로드
RDS_ENDPOINT=$(cd aws-terraform && terraform output -raw rds_endpoint)
RDS_PORT=$(cd aws-terraform && terraform output -raw rds_port)
S3_BUCKET=$(cd aws-terraform && terraform output -raw s3_bucket)
RDS_PASSWORD=$(cd aws-terraform && terraform output -raw rds_password)

# 🔍 치환 함수
replace_placeholders() {
  infile="$1"
  tmpfile="$(mktemp)"

  while IFS= read -r line || [ -n "$line" ]; do
    line=$(echo "$line" | sed "s|YOUR_RDS_ENDPOINT|$RDS_ENDPOINT|g")
    line=$(echo "$line" | sed "s|YOUR_RDS_PORT|$RDS_PORT|g")
    line=$(echo "$line" | sed "s|YOUR_S3_BUCKET_NAME|$S3_BUCKET|g")
    line=$(echo "$line" | sed "s|YOUR_RDS_PASSWORD|$RDS_PASSWORD|g")
    printf "%s\n" "$line" >> "$tmpfile"
  done < "$infile"

  mv "$tmpfile" "$infile"
}

# 📂 대상 파일 (줄바꿈 포함, **반드시 배열 아님**)
for file in \
  kubeflow-manifests/apps/katib/upstream/installs/katib-cert-manager-external-db/secrets.env \
  kubeflow-manifests/apps/pipeline/upstream/env/platform-agnostic-multi-user/pipeline-install-config.yaml \
  kubeflow-manifests/apps/pipeline/upstream/env/platform-agnostic-multi-user/secret.env \
  keycloak/values.yaml \
  mlflow/values.yaml \
  tests/mysql.yaml
do
  echo "🔧 Processing $file"
  replace_placeholders "$file"
done