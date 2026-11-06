# One-time bootstrap, run ONCE by the account owner in AWS CloudShell (see infra/README.md).
# Creates the least-privilege IAM user that infra/server/ runs as, and the cost alarm.
# No access key is created here: you create it in the console, so its secret never lands in
# Terraform state.

terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = { source = "hashicorp/aws", version = "= 6.69.1" }
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { project = "sandbox-analyst", managed_by = "terraform-bootstrap" } }
}

variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "budget_email" {
  type        = string
  description = "Where cost alerts go."
}

variable "monthly_budget_usd" {
  type    = number
  default = 15
}

data "aws_caller_identity" "current" {}

resource "aws_iam_user" "deployer" {
  name = "sandbox-analyst-deployer"
  path = "/sandbox-analyst/"
}

# Only what infra/server needs, only in one region, only the instance type we chose.
data "aws_iam_policy_document" "deployer" {
  statement {
    sid       = "ReadOnlyDescribe"
    actions   = ["ec2:Describe*", "sts:GetCallerIdentity"]
    resources = ["*"]
  }

  statement {
    sid = "ManageNetworkingAndKeys"
    actions = [
      "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup",
      "ec2:AuthorizeSecurityGroupIngress", "ec2:RevokeSecurityGroupIngress",
      "ec2:AuthorizeSecurityGroupEgress", "ec2:RevokeSecurityGroupEgress",
      "ec2:ModifySecurityGroupRules", "ec2:UpdateSecurityGroupRuleDescriptionsIngress",
      "ec2:ImportKeyPair", "ec2:DeleteKeyPair",
      "ec2:AllocateAddress", "ec2:ReleaseAddress",
      "ec2:AssociateAddress", "ec2:DisassociateAddress",
      "ec2:CreateTags", "ec2:DeleteTags",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.region]
    }
  }

  statement {
    sid       = "LaunchOnlyTheChosenInstanceType"
    actions   = ["ec2:RunInstances"]
    resources = ["arn:aws:ec2:${var.region}:${data.aws_caller_identity.current.account_id}:instance/*"]
    condition {
      test     = "StringEquals"
      variable = "ec2:InstanceType"
      values   = ["t4g.small"]
    }
  }

  # The other resources a launch touches. Listed by type on purpose: a wildcard such as
  # "...:${account}:*" would also match instance/* and bypass the instance-type rule above.
  statement {
    sid     = "LaunchSupportingResources"
    actions = ["ec2:RunInstances"]
    resources = concat(
      ["arn:aws:ec2:${var.region}::image/*"],
      [for type in ["network-interface", "security-group", "subnet", "volume", "key-pair"] :
      "arn:aws:ec2:${var.region}:${data.aws_caller_identity.current.account_id}:${type}/*"],
    )
  }

  statement {
    sid = "ManageOwnInstancesOnly"
    actions = [
      "ec2:TerminateInstances", "ec2:StopInstances", "ec2:StartInstances",
      "ec2:RebootInstances", "ec2:ModifyInstanceAttribute",
    ]
    resources = ["arn:aws:ec2:${var.region}:${data.aws_caller_identity.current.account_id}:instance/*"]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/project"
      values   = ["sandbox-analyst"]
    }
  }

  statement {
    sid       = "LookUpUbuntuImage"
    actions   = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = ["arn:aws:ssm:${var.region}::parameter/aws/service/canonical/*"]
  }
}

resource "aws_iam_user_policy" "deployer" {
  name   = "sandbox-analyst-deployer"
  user   = aws_iam_user.deployer.name
  policy = data.aws_iam_policy_document.deployer.json
}

# Cost alarm on real usage (credits excluded, so the alarm is not silenced by them).
resource "aws_budgets_budget" "monthly" {
  name         = "sandbox-analyst-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_types {
    include_credit = false
    include_refund = false
  }

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.budget_email]
    }
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}

output "deployer_user" {
  value = aws_iam_user.deployer.name
}

output "next_step" {
  value = "Console > IAM > Users > ${aws_iam_user.deployer.name} > Security credentials > Create access key (CLI). Put it in ~/.aws/credentials on your machine under [sandbox-analyst]."
}
