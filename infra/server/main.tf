# The API server (ADR-026). Runs as the least-privilege `sandbox-analyst-deployer` user created by
# infra/bootstrap. Secrets are NOT passed here (they would end up in Terraform state and EC2 user
# data); deploy/.env is copied over SSH after launch (infra/README.md).

terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = { source = "hashicorp/aws", version = "= 6.69.1" }
  }
}

provider "aws" {
  region  = var.region
  profile = var.aws_profile
  default_tags { tags = { project = "sandbox-analyst", managed_by = "terraform" } }
}

variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "aws_profile" {
  type    = string
  default = "sandbox-analyst"
}

variable "ssh_cidr" {
  type        = string
  description = "Your public IP as a /32: the only address allowed to SSH in."
  validation {
    condition     = can(cidrhost(var.ssh_cidr, 0)) && endswith(var.ssh_cidr, "/32")
    error_message = "Use a single address, e.g. 203.0.113.7/32."
  }
}

variable "ssh_public_key_path" {
  type    = string
  default = "~/.ssh/sandbox-analyst.pub"
}

variable "repo_url" {
  type    = string
  default = "https://github.com/singhsrj/sandbox-analyst.git"
}

# Canonical's published Ubuntu 24.04 LTS image for 64-bit Arm (always the current build).
data "aws_ssm_parameter" "ubuntu_arm64" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id"
}

data "aws_vpc" "default" {
  default = true
}

resource "aws_security_group" "api" {
  name        = "sandbox-analyst-api"
  description = "HTTPS for the API, SSH from one address"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "HTTP: certificate challenge and redirect to HTTPS"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "SSH from the operator only"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_cidr]
  }
  egress {
    description = "Outbound: Neon, E2B, Bedrock, Langfuse, package mirrors"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_key_pair" "operator" {
  key_name   = "sandbox-analyst"
  public_key = file(pathexpand(var.ssh_public_key_path))
}

resource "aws_instance" "api" {
  ami                    = data.aws_ssm_parameter.ubuntu_arm64.value
  instance_type          = "t4g.small" # the deployer user can launch nothing else
  key_name               = aws_key_pair.operator.key_name
  vpc_security_group_ids = [aws_security_group.api.id]
  user_data              = templatefile("${path.module}/user_data.sh", { repo_url = var.repo_url })

  metadata_options {
    http_tokens   = "required" # IMDSv2 only
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 20
    encrypted   = true
  }

  tags = { Name = "sandbox-analyst-api" }

  lifecycle {
    ignore_changes = [ami] # a newer Ubuntu build must not replace the running server
  }
}

resource "aws_eip" "api" {
  domain = "vpc"
  tags   = { Name = "sandbox-analyst-api" }
}

resource "aws_eip_association" "api" {
  instance_id   = aws_instance.api.id
  allocation_id = aws_eip.api.id
}

output "public_ip" {
  value = aws_eip.api.public_ip
}

output "ssh" {
  value = "ssh -i ~/.ssh/sandbox-analyst ubuntu@${aws_eip.api.public_ip}"
}
