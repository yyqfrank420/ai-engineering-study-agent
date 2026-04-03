resource "google_billing_budget" "monthly" {
  count           = var.billing_account_id != "" && var.monthly_budget_amount > 0 ? 1 : 0
  billing_account = var.billing_account_id
  display_name    = "ai-study-agent-monthly-budget"

  budget_filter {
    projects = ["projects/${var.project_id}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(floor(var.monthly_budget_amount))
      nanos         = floor((var.monthly_budget_amount - floor(var.monthly_budget_amount)) * 1000000000)
    }
  }

  threshold_rules {
    threshold_percent = 0.25
  }

  threshold_rules {
    threshold_percent = 0.50
  }

  threshold_rules {
    threshold_percent = 0.75
  }

  threshold_rules {
    threshold_percent = 1.00
  }
}
