#!/bin/bash

parent_path=$(cd "$(dirname "${BASH_SOURCE[0]}")"; pwd -P)
cd "$parent_path"

## domain
export DOMAIN=$(gcloud domains list-user-verified --format="value(id)")
## cloud sql private ip
export CLOUD_SQL_IP=$(cd ~/llmops-manifests/gke-terraform && terraform output -raw gcsCloudSqlPrivateIP)
## oauth client id
read -p "Enter Oauth Client ID: " client_id
## oauth client secret id
read -p "Enter Oauth Client Secret: " client_secret
## user email id
export EMAIL=$(gcloud config list core/account --format="value(core.account)")

## istio
sed -i 's/<<domain>>/'$DOMAIN'/g' ../common/istio-1-22/istio-install/overlays/gke-gateway/kubeflow-gateway.yaml
## kserve
sed -i 's/<<domain>>/'$DOMAIN'/' ../common/knative/knative-serving/overlays/gateways/patches/config-patch.yaml
sed -i 's/<<domain>>/'$DOMAIN'/' ../common/knative/knative-serving/overlays/gateways/gateway.yaml
## dex
sed -i 's/<<domain>>/'$DOMAIN'/g' ../common/dex/overlays/google-oauth2-client/config-map.yaml
sed -i 's/<<client_id>>/'$client_id'/g' ../common/dex/overlays/google-oauth2-client/config-map.yaml
sed -i 's/<<client_secret>>/'$client_secret'/g' ../common/dex/overlays/google-oauth2-client/config-map.yaml
## oauth2-proxy
sed -i 's/<<domain>>/'$DOMAIN'/g' ../common/oauth2-proxy/components/istio-external-auth/requestauthentication.dex-jwt.yaml
sed -i 's/<<domain>>/'$DOMAIN'/g' ../common/oauth2-proxy/base/oauth2_proxy.cfg
sed -i 's/<<domain>>/'$DOMAIN'/g' ../common/oauth2-proxy/components/istio-external-auth/authorizationpolicy.istio-ingressgateway-oauth2-proxy.yaml
sed -i 's/<<domain>>/'$DOMAIN'/g' ../common/oauth2-proxy/components/istio-external-auth/authorizationpolicy.istio-ingressgateway-require-jwt.yaml
sed -i 's/<<client_id>>/'$client_id'/g' ../common/oauth2-proxy/base/kustomization.yaml
sed -i 's/<<client_secret>>/'$client_secret'/g' ../common/oauth2-proxy/base/kustomization.yaml
## katib
sed -i 's/<<gcsCloudSqlPrivateIP>>/'$CLOUD_SQL_IP'/g' ../apps/katib/upstream/installs/katib-cert-manager-external-db/secrets.env
## pipeline
sed -i 's/<<gcsCloudSqlPrivateIP>>/'$CLOUD_SQL_IP'/g' ../apps/pipeline/upstream/env/platform-agnostic-multi-user/params.env
## user profile
sed -i 's/<<google_email>>/'$EMAIL'/g' ../common/user-namespace/base/params.env
## model-registry
sed -i 's/<<gcsCloudSqlPrivateIP>>/'$CLOUD_SQL_IP'/g' ../apps/model-registry/upstream/overlays/external-db/params.env