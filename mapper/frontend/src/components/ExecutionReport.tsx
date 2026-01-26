import React, { useState } from 'react'
import './ExecutionReport.css'

// Types for the new report format
interface StepResult {
  action: string
  step: any
  success: boolean
  error: string | null
  ui_check?: { pass: boolean }
  api_check?: { pass: boolean }
  db_check?: { pass: boolean }
  db_verification?: { success: boolean }
}

interface TestResult {
  test_case_id: string
  success: boolean
  steps_executed: StepResult[]
  steps_failed?: { step_index: number; error: string; step: any }[]
  error?: string
}

interface PersonaResult {
  persona: string
  test_results: TestResult[]
}

// Types for the old report format (backward compatibility)
interface VerificationDetail {
  success: boolean
  checked: boolean
  details?: any
}

interface ScenarioResult {
  scenario_id: string
  purpose: string
  success: boolean
  final_result: string
  verification: {
    ui?: VerificationDetail
    api?: VerificationDetail
    db?: VerificationDetail
  }
  error?: string
}

interface ExecutionReportProps {
  report: {
    mission_id: string
    overall_success: boolean
    // New format
    persona_results?: Record<string, PersonaResult>
    // Old format
    scenario_results?: Record<string, ScenarioResult>
    triple_check?: {
      database?: { success: boolean }
      api?: { success: boolean }
      ui?: { success: boolean }
    }
  }
}

export default function ExecutionReport({ report }: ExecutionReportProps) {
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>({})

  const toggleItem = (id: string) => {
    setExpandedItems(prev => ({
      ...prev,
      [id]: !prev[id]
    }))
  }

  // Check which format we have
  const isNewFormat = !!report.persona_results
  
  if (isNewFormat && report.persona_results) {
    return (
      <div className="execution-report">
        <ReportHeader report={report} />
        
        <div className="er-personas">
          {Object.values(report.persona_results).map((personaRes) => (
            <div key={personaRes.persona} className="er-persona-section">
              <h4 className="er-persona-title">👤 {personaRes.persona}</h4>
              <div className="er-scenarios">
                {personaRes.test_results.map((test, idx) => (
                  <TestCaseRow 
                    key={`${personaRes.persona}-${idx}`} 
                    test={test} 
                    isExpanded={!!expandedItems[`${personaRes.persona}-${idx}`]}
                    onToggle={() => toggleItem(`${personaRes.persona}-${idx}`)}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  // Fallback to old format
  const scenarios = Object.values(report.scenario_results || {})
  return (
    <div className="execution-report">
      <ReportHeader report={report} />
      <div className="er-scenarios">
        {scenarios.map((scenario) => (
          <OldScenarioRow 
            key={scenario.scenario_id} 
            scenario={scenario}
            isExpanded={!!expandedItems[scenario.scenario_id]}
            onToggle={() => toggleItem(scenario.scenario_id)}
          />
        ))}
      </div>
    </div>
  )
}

function ReportHeader({ report }: { report: any }) {
  return (
    <div className={`er-header ${report.overall_success ? 'success' : 'failed'}`}>
      <div className="er-status-icon">
        {report.overall_success ? '✓' : '✗'}
      </div>
      <div className="er-header-content">
        <h3>{report.overall_success ? 'Execution Passed' : 'Execution Failed'}</h3>
        <span className="er-mission-id">Mission: {report.mission_id}</span>
      </div>
    </div>
  )
}

// Helper to check if a step is a verification step
function isVerificationStep(step: StepResult) {
  const action = step.action.toLowerCase()
  // Explicit verification actions
  if (['verify_ui', 'assert_visible', 'assert_url_contains', 'verify_api_value_in_ui', 'assert_api_field_not_shown'].includes(action)) {
    return true
  }
  // Any step with explicit checks
  if (step.ui_check || step.api_check || step.db_check || step.db_verification) {
    return true
  }
  return false
}

function TestCaseRow({ test, isExpanded, onToggle }: { test: TestResult, isExpanded: boolean, onToggle: () => void }) {
  // Derive status for UI/API/DB
  let uiStatus: 'pass' | 'fail' | 'skipped' = 'skipped'
  let apiStatus: 'pass' | 'fail' | 'skipped' = 'skipped'
  let dbStatus: 'pass' | 'fail' | 'skipped' = 'skipped'

  // Helper to update status (fail overrides pass, pass overrides skipped)
  const updateStatus = (current: string, result: boolean) => {
    if (current === 'fail') return 'fail'
    if (!result) return 'fail'
    return 'pass'
  }

  test.steps_executed.forEach(step => {
    // Check explicit verification objects
    if (step.ui_check) uiStatus = updateStatus(uiStatus, step.ui_check.pass)
    if (step.api_check) apiStatus = updateStatus(apiStatus, step.api_check.pass)
    if (step.db_check) dbStatus = updateStatus(dbStatus, step.db_check.pass)
    if (step.db_verification) dbStatus = updateStatus(dbStatus, step.db_verification.success)

    // Infer from action types if not explicitly verified
    const action = step.action.toLowerCase()
    
    // UI Actions
    if (['goto', 'click', 'fill', 'wait_visible', 'assert_visible', 'verify_ui'].includes(action)) {
      if (uiStatus === 'skipped') uiStatus = step.success ? 'pass' : 'fail'
      else if (!step.success) uiStatus = 'fail'
    }
    
    // API Actions
    if (action.includes('api')) {
      if (apiStatus === 'skipped') apiStatus = step.success ? 'pass' : 'fail'
      else if (!step.success) apiStatus = 'fail'
    }
  })

  // Get failure reason
  const failureReason = test.steps_failed?.[0]?.error || test.error || (test.success ? null : "Unknown error")

  // Filter steps to show only relevant verifications or failures
  const relevantSteps = test.steps_executed.filter(step => {
    // Always show failed steps
    if (!step.success) return true
    // Show verification steps
    return isVerificationStep(step)
  })

  return (
    <div className={`er-scenario ${test.success ? 'success' : 'failed'}`}>
      <div className="er-scenario-header" onClick={onToggle}>
        <div className={`er-scenario-status ${test.success ? 'success' : 'failed'}`}>
          {test.success ? 'PASS' : 'FAIL'}
        </div>
        <div className="er-scenario-info">
          <div className="er-scenario-purpose">{test.test_case_id}</div>
          {!test.success && (
            <div className="er-scenario-error-preview">
              {failureReason}
            </div>
          )}
        </div>
        <div className="er-scenario-toggle">
          {isExpanded ? '−' : '+'}
        </div>
      </div>

      {isExpanded && (
        <div className="er-scenario-details">
          {!test.success && (
            <div className="er-error-message">
              <strong>Failure Reason:</strong> {failureReason}
            </div>
          )}

          <div className="er-verifications">
            <StatusRow type="UI" icon="🖥️" status={uiStatus} />
            <StatusRow type="API" icon="🔌" status={apiStatus} />
            <StatusRow type="DB" icon="💾" status={dbStatus} />
          </div>

          <div className="er-steps-list">
            <h5>Verification Details:</h5>
            {relevantSteps.length === 0 ? (
              <div className="er-no-steps">No verification steps recorded.</div>
            ) : (
              relevantSteps.map((step, i) => (
                <div key={i} className={`er-step-item ${step.success ? 'pass' : 'fail'}`}>
                  <div className="er-step-main">
                    <span className="er-step-icon">{step.success ? '✓' : '✗'}</span>
                    <span className="er-step-desc">
                      {step.step.description || formatAction(step.action)}
                    </span>
                  </div>
                  {!step.success && step.error && (
                    <div className="er-step-error">{step.error}</div>
                  )}
                  
                  {/* Show detailed check results if available */}
                  {step.api_check && (
                    <div className="er-step-details">
                      <span className="er-detail-label">API Check:</span>
                      <span className={step.api_check.pass ? 'pass' : 'fail'}>
                        {step.api_check.pass ? 'Passed' : 'Failed'}
                      </span>
                      {/* We could show the value here if available in the type, but it's not in StepResult yet */}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function formatAction(action: string) {
  return action.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())
}

function StatusRow({ type, icon, status }: { type: string, icon: string, status: 'pass' | 'fail' | 'skipped' }) {
  if (status === 'skipped') return null
  
  return (
    <div className={`er-verification-row ${status === 'pass' ? 'success' : 'failed'}`}>
      <div className="er-v-type">
        <span>{icon}</span> {type}
      </div>
      <div className="er-v-status">
        {status === 'pass' ? 'Passed' : 'Failed'}
      </div>
    </div>
  )
}

function OldScenarioRow({ scenario, isExpanded, onToggle }: { scenario: ScenarioResult, isExpanded: boolean, onToggle: () => void }) {
  return (
    <div className={`er-scenario ${scenario.success ? 'success' : 'failed'}`}>
      <div className="er-scenario-header" onClick={onToggle}>
        <div className={`er-scenario-status ${scenario.success ? 'success' : 'failed'}`}>
          {scenario.success ? 'PASS' : 'FAIL'}
        </div>
        <div className="er-scenario-info">
          <div className="er-scenario-purpose">{scenario.purpose || scenario.scenario_id}</div>
          {!scenario.success && (
            <div className="er-scenario-error-preview">
              {scenario.final_result || scenario.error || 'Test failed'}
            </div>
          )}
        </div>
        <div className="er-scenario-toggle">
          {isExpanded ? '−' : '+'}
        </div>
      </div>

      {isExpanded && (
        <div className="er-scenario-details">
          <div className="er-result-message">
            <strong>Result:</strong> {scenario.final_result}
          </div>
          
          {scenario.error && (
            <div className="er-error-message">
              <strong>Error:</strong> {scenario.error}
            </div>
          )}

          <div className="er-verifications">
            <OldVerificationRow type="UI" icon="🖥️" data={scenario.verification?.ui} />
            <OldVerificationRow type="API" icon="🔌" data={scenario.verification?.api} />
            <OldVerificationRow type="DB" icon="💾" data={scenario.verification?.db} />
          </div>
        </div>
      )}
    </div>
  )
}

function OldVerificationRow({ type, icon, data }: { type: string, icon: string, data?: VerificationDetail }) {
  if (!data || !data.checked) return null

  return (
    <div className={`er-verification-row ${data.success ? 'success' : 'failed'}`}>
      <div className="er-v-type">
        <span>{icon}</span> {type}
      </div>
      <div className="er-v-status">
        {data.success ? 'Verified' : 'Failed'}
      </div>
    </div>
  )
}
