resource "google_compute_network" "vpc_network" {
  name                    = "gke-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "subnet" {
  name          = "gke-subnetwork"
  ip_cidr_range = "10.0.1.0/24"
  region        = var.region
  network       = google_compute_network.vpc_network.name

  secondary_ip_range {
    range_name    = "services-range"
    ip_cidr_range = "10.105.176.0/20"
  }

  secondary_ip_range {
    range_name    = "pod-ranges"
    ip_cidr_range = "10.128.0.0/14"
  }
}

##### GKE CLUSTER #####

resource "google_container_cluster" "gke_cluster" {
  name     = "gke-cluster"
  location = var.region

  network    = google_compute_network.vpc_network.name
  subnetwork = google_compute_subnetwork.subnet.name

  remove_default_node_pool = true
  initial_node_count       = 1

  deletion_protection = false
  
  gateway_api_config {
    channel = "CHANNEL_STANDARD"
  }
  
  addons_config {
    gcp_filestore_csi_driver_config {
      enabled = true
    }
  }
  
  ip_allocation_policy {
    services_secondary_range_name = google_compute_subnetwork.subnet.secondary_ip_range.0.range_name
    cluster_secondary_range_name  = google_compute_subnetwork.subnet.secondary_ip_range.1.range_name
  }
}

resource "google_container_node_pool" "node_pool" {
  name       = "my-node-pool"
  location   = var.region
  cluster    = google_container_cluster.gke_cluster.name
  node_count = var.gke_node_count

  node_config {
    preemptible  = true
    machine_type = var.gke_node_machine_type
    disk_size_gb = 50
  }

  autoscaling {
    min_node_count  = 0
    max_node_count  = var.gke_node_count * 2
    location_policy = "BALANCED"
  }

  management {
    auto_upgrade = false
  }
}

##### CLOUD SQL #####

resource "google_compute_global_address" "private_ip_address" {
  address       = "10.175.0.0"
  name          = "db-ip-address"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.vpc_network.id
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.vpc_network.id
  service                 = "servicenetworking.googleapis.com"
  depends_on              = [google_compute_global_address.private_ip_address]
  reserved_peering_ranges = [google_compute_global_address.private_ip_address.name]
}
resource "google_sql_database_instance" "kubeflow_db" {
  name             = "kubeflow-database-instance"
  region           = var.region
  database_version = "MYSQL_8_0"
  depends_on       = [google_service_networking_connection.private_vpc_connection]
  settings {
    tier = "db-f1-micro"
    ip_configuration {
      ipv4_enabled                                  = "false"
      private_network                               = google_compute_network.vpc_network.id
      enable_private_path_for_google_cloud_services = true
    }
  }

  deletion_protection = "false"
}

resource "google_sql_user" "pipeline_user" {
  name     = "pipeline"
  instance = google_sql_database_instance.kubeflow_db.name
  host     = "%"
  password = "pipeline"
}
resource "google_sql_database" "pipeline_database" {
  name     = "mlpipeline"
  instance = google_sql_database_instance.kubeflow_db.name
}
resource "google_sql_database" "cache_database" {
  name     = "cachedb"
  instance = google_sql_database_instance.kubeflow_db.name
}
resource "google_sql_database" "meta_database" {
  name     = "metadb"
  instance = google_sql_database_instance.kubeflow_db.name
}
resource "google_sql_user" "katib_user" {
  name     = "katib"
  instance = google_sql_database_instance.kubeflow_db.name
  host     = "%"
  password = "katib"
}
resource "google_sql_database" "katib_database" {
  name     = "katib"
  instance = google_sql_database_instance.kubeflow_db.name
}
resource "google_sql_user" "mlflow_user" {
  name     = "mlflow"
  instance = google_sql_database_instance.kubeflow_db.name
  host     = "%"
  password = "mlflow"
}
resource "google_sql_database" "mlflow_database" {
  name     = "mlflow"
  instance = google_sql_database_instance.kubeflow_db.name
}
