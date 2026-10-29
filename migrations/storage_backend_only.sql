-- REVIEW ONLY. Not executed by Alembic or server startup.
-- Apply only after approval for the exact bucket and its existing consumers.
-- Replace the placeholder first. No existing policy is dropped or altered.
-- Private buckets alone do not override an existing permissive RLS policy.
-- Backend service_role bypasses RLS; app bearer sessions are NOT Supabase JWTs.
CREATE POLICY swing_private_backend_only
ON storage.objects AS RESTRICTIVE FOR ALL TO anon, authenticated
USING (bucket_id <> 'REPLACE_WITH_APPROVED_PRIVATE_BUCKET')
WITH CHECK (bucket_id <> 'REPLACE_WITH_APPROVED_PRIVATE_BUCKET');
