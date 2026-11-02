# Foundation Terraform — LinkPulse (TV5)
# Phần còn lại sau khi WAF chuyển vào infra/edge.yaml (chỉ giữ một định nghĩa WAF duy nhất).
# Ở đây chỉ dựng AWS Budget: $5/tháng lọc theo region workload + 1 budget tổng chống bill shock.
# Dùng sau khi đã chạy scripts/setup_aws_foundation.sh (IAM user/group/MFA).
#   terraform init && terraform plan -var='alert_emails=["a@x","b@x"]' && terraform apply

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

variable "project" { default = "linkpulse" }
variable "workload_region" { default = "ap-southeast-2" }
variable "budget_limit" { default = "5" }
variable "alert_emails" { type = list(string) }

provider "aws" { region = var.workload_region }
provider "aws" { alias = "use1" region = "us-east-1" }   # Budgets chỉ có endpoint ở us-east-1

locals { name = var.project }

# ---------------- Budgets: $5 region workload + budget tổng ----------------
resource "aws_budgets_budget" "sg" {
  provider     = aws.use1
  name         = "${local.name}-monthly-${var.workload_region}-$${var.budget_limit}"
  budget_type  = "COST"
  limit_amount = var.budget_limit
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter { name = "Region" values = [var.workload_region] }

  dynamic "notification" {
    for_each = [
      { type = "FORECASTED", pct = 80 },
      { type = "ACTUAL", pct = 100 },
    ]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value.pct
      threshold_type             = "PERCENTAGE"
      notification_type          = notification.value.type
      subscriber_email_addresses = var.alert_emails
    }
  }
}

resource "aws_budgets_budget" "total" {
  provider     = aws.use1
  name         = "${local.name}-monthly-total-$${var.budget_limit}"
  budget_type  = "COST"
  limit_amount = var.budget_limit
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.alert_emails
  }
}
