# Foundation Terraform — Smart URL Serverless (TV5, Week 1)
# Region workload: ap-southeast-1 (provider default)
# WAF Web ACL cho CloudFront BẮT BUỘC ở us-east-1 (provider alias use1), Scope = CLOUDFRONT.
# Budget $5/tháng lọc Region ap-southeast-1 + 1 budget tổng chống bill shock.
# Dùng sau khi đã chạy scripts/setup_aws_foundation.sh (IAM user/group/MFA).
#   terraform init && terraform plan -var='alert_emails=["a@x","b@x"]' && terraform apply

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

variable "project" { default = "linkpulse" }
variable "workload_region" { default = "ap-southeast-1" }
variable "budget_limit" { default = "5" }
variable "alert_emails" { type = list(string) }

provider "aws" { region = var.workload_region }                          # Singapore: workload
provider "aws" { alias = "use1" region = "us-east-1" }                   # Virginia: WAF + Budgets

locals { name = var.project }

# ---------------- WAF Web ACL (us-east-1, scope CLOUDFRONT) ----------------
resource "aws_wafv2_web_acl" "edge" {
  provider    = aws.use1
  name        = "${local.name}-edge"
  description = "TV5 Week1: bao ve CloudFront (Rate-based + Managed Rules)"
  scope       = "CLOUDFRONT"

  default_action { allow {} }

  # 0. IP Reputation — chặn botnet/scanner đã biết
  rule {
    name     = "AWS-IPReputation"
    priority = 0
    override_action { none {} }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesAmazonIpReputationList"
      }
    }
    visibility_config { cloudwatch_metrics_enabled = true metric_name = "waf-iprep" sampled_requests_enabled = true }
  }

  # 1. Rate-based: POST /api/shorten — 100 req/5'/IP
  rule {
    name     = "RL-Shorten"
    priority = 1
    action { block {} }
    statement {
      rate_based_statement {
        limit              = 100
        aggregate_key_type = "IP"
        scope_down_statement {
          byte_match_statement {
            search_string = "/api/shorten"
            field_to_match { uri_path {} }
            positional_constraint = "STARTS_WITH"
            text_transformation { priority = 0 type = "NONE" }
          }
        }
      }
    }
    visibility_config { cloudwatch_metrics_enabled = true metric_name = "waf-rl-shorten" sampled_requests_enabled = true }
  }

  # 2. Rate-based: GET /{code} — 1000 req/5'/IP.
  # WAF scope-down không có "regex path", nên dùng NOT: mọi path KHÔNG bắt đầu
  # bằng /api/ (tức là redirect /{code} + static). Static S3 đã cache nên thực
  # tế rule này chủ yếu đếm redirect — đúng mục đích chống enumeration (T-03).
  rule {
    name     = "RL-Redirect"
    priority = 2
    action { block {} }
    statement {
      rate_based_statement {
        limit              = 1000
        aggregate_key_type = "IP"
        scope_down_statement {
          not_statement {
            statement {
              byte_match_statement {
                search_string         = "/api/"
                field_to_match { uri_path {} }
                positional_constraint = "STARTS_WITH"
                text_transformation { priority = 0 type = "NONE" }
              }
            }
          }
        }
      }
    }
    visibility_config { cloudwatch_metrics_enabled = true metric_name = "waf-rl-redirect" sampled_requests_enabled = true }
  }

  # 3. Known Bad Inputs
  rule {
    name     = "AWS-KnownBadInputs"
    priority = 3
    override_action { none {} }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
      }
    }
    visibility_config { cloudwatch_metrics_enabled = true metric_name = "waf-badinputs" sampled_requests_enabled = true }
  }

  # 4. Common Rule Set (Count 1 tuần đầu rồi chuyển Block — đổi override_action sang none khi sẵn sàng)
  rule {
    name     = "AWS-CommonRuleSet"
    priority = 4
    override_action { count {} }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"
      }
    }
    visibility_config { cloudwatch_metrics_enabled = true metric_name = "waf-crs" sampled_requests_enabled = true }
  }

  visibility_config { cloudwatch_metrics_enabled = true metric_name = "waf-edge" sampled_requests_enabled = true }

  tags = { Project = "LinkPulse" }
}

# Gắn Web ACL vào CloudFront distribution (điền ID sau khi TV2 tạo distribution)
variable "cloudfront_distribution_id" { default = "" } # ví dụ E1234ABCD
resource "aws_wafv2_web_acl_association" "edge_cf" {
  count        = var.cloudfront_distribution_id == "" ? 0 : 1
  provider     = aws.use1
  resource_arn = "arn:aws:cloudfront::${data.aws_caller_identity.me.account_id}:distribution/${var.cloudfront_distribution_id}"
  web_acl_arn  = aws_wafv2_web_acl.edge.arn
}

data "aws_caller_identity" "me" {}

# WAF logging → S3 (lifecycle 30 ngày → Glacier).
# Lưu ý: WAF chỉ ghi log được khi bucket policy cho phép delivery.logs.amazonaws.com;
# resource aws_s3_bucket_policy dưới là bắt buộc, đừng xóa khi apply thật.
resource "aws_s3_bucket" "waf_logs" {
  provider = aws.use1
  bucket   = "${local.name}-waf-logs-${data.aws_caller_identity.me.account_id}"
  tags     = { Project = "LinkPulse" }
}
resource "aws_s3_bucket_policy" "waf_logs" {
  provider = aws.use1
  bucket   = aws_s3_bucket.waf_logs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowWAFLogging"
      Effect    = "Allow"
      Principal = { Service = "delivery.logs.amazonaws.com" }
      Action    = ["s3:PutObject"]
      Resource  = "${aws_s3_bucket.waf_logs.arn}/AWSLogs/${data.aws_caller_identity.me.account_id}/*"
      Condition = { StringEquals = { "s3:x-amz-acl" = "bucket-owner-full-control" } }
    }]
  })
}
resource "aws_wafv2_web_acl_logging_configuration" "edge_logs" {
  provider                = aws.use1
  resource_arn            = aws_wafv2_web_acl.edge.arn
  log_destination_configs = ["${aws_s3_bucket.waf_logs.arn}"]
}

# ---------------- Budgets: $5 Singapore + budget tổng ----------------
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
      comparison_operator       = "GREATER_THAN"
      threshold                 = notification.value.pct
      threshold_type            = "PERCENTAGE"
      notification_type         = notification.value.type
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
