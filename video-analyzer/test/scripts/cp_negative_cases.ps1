Param(
  [string]$CpBase = "http://127.0.0.1:8080"
)
$ErrorActionPreference = 'Stop'

function Assert-Code($resp, [int]$code) {
  if ($resp.StatusCode -ne $code) { throw "EXPECT $code GOT $($resp.StatusCode): $($resp.Content)" }
}

# 1) invalid subscription profile -> 404
$r1 = iwr -UseBasicParsing "$CpBase/api/subscriptions" -Method Post -Body '{"stream_id":"s_bad","profile":"no_such","source_id":"camera_01"}' -ContentType 'application/json' -SkipHttpErrorCheck:$true
Assert-Code $r1 404

# 2) apply_pipeline missing args -> 400
$r2 = iwr -UseBasicParsing "$CpBase/api/control/apply_pipeline" -Method Post -Body '{}' -ContentType 'application/json' -SkipHttpErrorCheck:$true
Assert-Code $r2 400

# 3) delete unknown pipeline -> 404
$r3 = iwr -UseBasicParsing "$CpBase/api/control/pipeline?pipeline_name=no_such_pipeline" -Method Delete -SkipHttpErrorCheck:$true
Assert-Code $r3 404

# 4) sources:disable unknown attach -> 404
$r4 = iwr -UseBasicParsing "$CpBase/api/sources:disable" -Method Post -Body '{"attach_id":"no_such"}' -ContentType 'application/json' -SkipHttpErrorCheck:$true
Assert-Code $r4 404

Write-Host "[cp_negative_cases] PASS" -ForegroundColor Green

