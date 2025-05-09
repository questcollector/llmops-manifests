# Filter out local zones, which are not currently supported 
# with managed node groups
data "aws_availability_zones" "available" {
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

locals {
  cluster_name = "kubeflow-eks"
  vpc_cidr     = "10.0.0.0/16"
}

## VPC, Subnet
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.19.0"

  name = "kubeflow-eks-vpc"

  cidr = local.vpc_cidr
  azs  = slice(data.aws_availability_zones.available.names, 0, 3)

  private_subnets  = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  public_subnets   = ["10.0.4.0/24", "10.0.5.0/24", "10.0.6.0/24"]
  database_subnets = ["10.0.7.0/24", "10.0.8.0/24", "10.0.9.0/24"]

  enable_nat_gateway     = true
  single_nat_gateway     = true
  one_nat_gateway_per_az = false
  enable_dns_hostnames   = true

  create_database_subnet_group = true

  public_subnet_tags = {
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
    "kubernetes.io/role/elb"                      = 1
  }

  private_subnet_tags = {
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
    "kubernetes.io/role/internal-elb"             = 1
  }

  database_subnet_tags = {
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
    "kubernetes.io/role/internal-elb"             = 1
  }
}

## EKS
## Node Pool
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "20.34.0"

  cluster_name    = local.cluster_name
  cluster_version = "1.32"

  vpc_id                                   = module.vpc.vpc_id
  subnet_ids                               = module.vpc.private_subnets
  cluster_endpoint_public_access           = true
  enable_cluster_creator_admin_permissions = true

  eks_managed_node_group_defaults = {
    ami_type = "AL2_x86_64"
  }

  cluster_addons = {
    coredns                = {}
    eks-pod-identity-agent = {}
    kube-proxy             = {}
    vpc-cni                = {}
  }

  node_iam_role_additional_policies = {
    AmazonEKS_CNI_Policy      = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
    AmazonEKSWorkerNodePolicy = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
  }

  eks_managed_node_groups = {
    one = {
      name           = "cpu-pool"
      instance_types = [var.instance_type]

      min_size     = 1
      max_size     = 6
      desired_size = 2
    }
    two = {
      name           = "serving-pool"
      ami_type       = "AL2_x86_64_GPU"
      capacity_type  = "SPOT"
      instance_types = ["g6.2xlarge"]

      min_size     = 0
      max_size     = 2
      desired_size = 0
    }
    three = {
      name           = "training-pool"
      ami_type       = "AL2_x86_64_GPU"
      capacity_type  = "SPOT"
      instance_types = ["g6.48xlarge"]

      min_size     = 0
      max_size     = 2
      desired_size = 0
    }
  }
}

resource "aws_security_group_rule" "istio" {
  description              = "Istio"
  type                     = "ingress"
  from_port                = 15017
  to_port                  = 15017
  protocol                 = "tcp"
  source_security_group_id = module.eks.cluster_security_group_id
  security_group_id        = module.eks.node_security_group_id
}

data "aws_iam_policy" "ebs_csi_policy" {
  arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

module "irsa-ebs-csi" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-assumable-role-with-oidc"
  version = "5.54.0"

  create_role                    = true
  role_name                      = "AmazonEKSEBSCSIRole-${module.eks.cluster_name}"
  provider_url                   = module.eks.oidc_provider
  role_policy_arns               = [data.aws_iam_policy.ebs_csi_policy.arn]
  oidc_fully_qualified_subjects  = ["system:serviceaccount:kube-system:ebs-csi-controller-sa"]
  oidc_fully_qualified_audiences = ["sts.amazonaws.com"]
}

resource "aws_eks_addon" "ebs-csi" {
  cluster_name             = module.eks.cluster_name
  addon_name               = "aws-ebs-csi-driver"
  service_account_role_arn = module.irsa-ebs-csi.iam_role_arn
  tags = {
    "eks_addon" = "ebs-csi"
    "terraform" = "true"
  }
}

data "aws_iam_policy" "s3_csi_policy" {
  arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}

module "irsa-s3-csi" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-assumable-role-with-oidc"
  version = "5.54.0"

  create_role                    = true
  role_name                      = "AmazonEKSS3CSIRole-${module.eks.cluster_name}"
  provider_url                   = module.eks.oidc_provider
  role_policy_arns               = [data.aws_iam_policy.s3_csi_policy.arn]
  oidc_fully_qualified_subjects  = ["system:serviceaccount:kube-system:s3-csi-driver-sa"]
  oidc_fully_qualified_audiences = ["sts.amazonaws.com"]
}

resource "aws_eks_addon" "s3-csi" {
  cluster_name             = module.eks.cluster_name
  addon_name               = "aws-mountpoint-s3-csi-driver"
  service_account_role_arn = module.irsa-s3-csi.iam_role_arn
  tags = {
    "eks_addon" = "mountpoint-s3-csi"
    "terraform" = "true"
  }
}

data "aws_iam_policy_document" "assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }

    actions = [
      "sts:AssumeRole",
      "sts:TagSession"
    ]
  }
}
resource "aws_iam_role" "s3_full_access" {
  name               = "eks-pod-identity-s3-full-access"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
}

resource "aws_iam_role_policy_attachment" "s3_role_attachment" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
  role       = aws_iam_role.s3_full_access.name
}

resource "aws_eks_pod_identity_association" "default_editor" {
  cluster_name    = module.eks.cluster_name
  namespace       = "pjt-llmops"
  service_account = "default-editor"
  role_arn        = aws_iam_role.s3_full_access.arn
}

resource "aws_eks_pod_identity_association" "mlflow" {
  cluster_name    = module.eks.cluster_name
  namespace       = "mlflow"
  service_account = "mlflow"
  role_arn        = aws_iam_role.s3_full_access.arn
}


## RDS
resource "random_string" "password" {
  length  = 10
  special = false
}

resource "aws_db_instance" "mysql" {
  identifier             = "kubeflow"
  allocated_storage      = 10
  engine                 = "mysql"
  engine_version         = "8.0"
  instance_class         = var.mysql_instance_type
  port                   = var.mysql_port
  username               = var.mysql_username
  password               = random_string.password.result
  skip_final_snapshot    = true
  apply_immediately      = true
  vpc_security_group_ids = ["${aws_security_group.mysql.id}"]
  db_subnet_group_name   = module.vpc.database_subnet_group_name
  parameter_group_name   = aws_db_parameter_group.mysql.name
}


resource "aws_db_parameter_group" "mysql" {
  name   = "kubeflow-parameter-group"
  family = "mysql8.0"

  parameter {
    name  = "max_connections"
    value = "1000"
  }
}


resource "aws_security_group" "mysql" {
  name        = "kubeflow_rds_sg"
  description = "Terraform RDS mysql sg"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port   = var.mysql_port
    to_port     = var.mysql_port
    protocol    = "tcp"
    cidr_blocks = [local.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [local.vpc_cidr]
  }
}

## S3
resource "random_string" "suffix" {
  length  = 10
  special = false
  upper   = false
}

resource "aws_s3_bucket" "kubeflow" {
  bucket = "kubeflow-${random_string.suffix.result}"

  tags = {
    Name        = "kubeflow"
    Environment = "Dev"
  }
}

# IAM user
resource "aws_iam_policy" "s3_full_access_to_bucket" {
  name        = "S3FullAccessToKubeflowBucket"
  description = "Full access to the specific S3 bucket"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "s3:*"
        Resource = [
          aws_s3_bucket.kubeflow.arn,
          "${aws_s3_bucket.kubeflow.arn}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_user" "s3_user" {
  name = "s3-user"
}

resource "aws_iam_user_policy_attachment" "attach_policy" {
  user       = aws_iam_user.s3_user.name
  policy_arn = aws_iam_policy.s3_full_access_to_bucket.arn
}


resource "aws_iam_access_key" "temp_key" {
  user = aws_iam_user.s3_user.name
}
