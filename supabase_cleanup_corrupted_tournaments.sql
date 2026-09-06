-- Clean up any accidentally created duplicate/nested tournament rows in Supabase
-- Run this in the Supabase SQL Editor:

DELETE FROM "Tournaments"
WHERE "Tournament_ID" LIKE '%(%)%'
   OR "Tournament_ID" LIKE '%[%]%'
   OR "Tournament_Name" LIKE '%(%)%[%]%';
