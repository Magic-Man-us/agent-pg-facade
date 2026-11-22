-- category: health
-- description: Buffer cache hit ratio for heap and index reads (aim above 0.99)
SELECT round(sum(heap_blks_hit)::numeric / nullif(sum(heap_blks_hit) + sum(heap_blks_read), 0), 4) AS heap_hit_ratio, round(sum(idx_blks_hit)::numeric / nullif(sum(idx_blks_hit) + sum(idx_blks_read), 0), 4) AS index_hit_ratio FROM pg_statio_user_tables