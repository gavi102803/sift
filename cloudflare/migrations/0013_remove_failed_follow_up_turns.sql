DELETE FROM concept_turns
WHERE role = 'user'
  AND EXISTS (
      SELECT 1
      FROM model_runs
      WHERE model_runs.concept_id = concept_turns.concept_id
        AND model_runs.idempotency_key = concept_turns.operation_key
        AND model_runs.kind = 'followUp'
        AND model_runs.status IN ('failed', 'cancelled')
  )
  AND NOT EXISTS (
      SELECT 1
      FROM concept_turns AS assistant
      WHERE assistant.concept_id = concept_turns.concept_id
        AND assistant.operation_key = concept_turns.operation_key
        AND assistant.role = 'assistant'
  );
