# Build playbook guide

playbook_version: 1.0.0
machine_playbook: docs/playbook/build-playbook.yaml
language: ASD-STE100 Simplified Technical English
criteria: AC-01 to AC-80

## 1. How to use these two files

This guide and the machine playbook describe the same build. The machine playbook is a YAML file. Claude Code reads it and does the steps. This guide is for people. Read this guide first. Then start the machine playbook.

The build has 12 phases, P0 to P11. Each phase has steps. Each step has an id, for example P1-S04. The ids are the same in both files. Each step has a goal, a list of actions, an expected result and a pass check. A step passes when its pass check passes.

Procedure to start a build with Claude Code:

1. Copy the folder docs/playbook into the new repo.
2. Open the machine playbook and fill each value in the profile block.
3. Tell Claude Code: "Read docs/playbook/build-playbook.yaml. Run the steps in order. Obey on_fail."
4. Read the run log after each phase.
5. Stop the build if a step fails and on_fail says stop.

Rules for a change to the playbook:

1. Change the machine playbook first.
2. Change this guide second.
3. Make sure the step ids and the titles are the same in both files.
4. Make sure each criterion id is in the table in section 5 and in one step of the machine playbook.
5. Increase the version in both files.

## 2. Scope and placeholders

The playbook describes a build process. It does not describe one business area. Words in angle brackets are placeholders. Fill them once, in the profile block of the machine playbook.

| Placeholder | Meaning |
|---|---|
| DOMAIN | A short name for the business area. It is used in file names. |
| FACT_TABLE | The table with one row per record. The engine assesses these records. |
| DIMENSION_TABLES | The lookup tables that join to the fact table. |
| KEY_METRIC | The one number the business asks for most. |
| BUSINESS_TERM | One term the business uses that needs one definition. |
| RULE_FAMILIES | The families of rules or metrics, for example C1 to C7. |
| DECISION_VOCABULARY | The only words a decision output can use. Leave it empty when there is no decision. |
| RESERVED_ACTIONS | The actions the system must never do and never write, for example: approve a payment. |
| NAMED_HUMAN_ROLE | The role of the person who makes the decision. |
| AS_OF_DATE | The fixed "today" for the data and the catalog. |
| DB_FILE | The path of the database file. |
| LLM_QUERY_PATH | True when free-text questions become SQL. False when the engine runs rules only. |

The playbook is a technical process. It does not interpret a control framework, a law or a policy. The people in Finance, Legal or Compliance interpret those documents. Ask them before you fill RULE_FAMILIES, DECISION_VOCABULARY and RESERVED_ACTIONS.

A worked example is given in some steps. The example is a register of records for one month, with rule families C1 to C7. The system runs each rule on each record. A named person reads the result and makes the decision. The system never makes the decision. The example uses no real names and no real amounts.

## 3. The four-part engine

The build produces one system with four parts. Keep the parts separate in the code.

1. **Deterministic core.** Code runs each rule and each metric on the data. The rules are SQL fragments from the catalog. All arithmetic happens here. The core reads the database read-only. It runs every rule on the whole data set. No value, no size and no age exempts a record from a rule.
2. **Language-model assist.** The model resolves terms, writes draft SQL or writes a short narrative. The model does not compute. The model does not decide. Hard guardrails limit what the model output can do.
3. **Lint.** A hard lint blocks output that is certainly wrong, after one repair attempt. A soft lint asks for one repair and never blocks.
4. **Human decision.** A named person receives a decision-ready output with the evidence. The person decides. The system records the name, the decision and the time.

The first project that used this flow had part 1, part 2 and part 3. The person read the SQL beside each answer. The example project uses all four parts. Part 4 is mandatory there.

## 4. Phases and steps

Each step below has the same four lines. **Goal** says why. **Do** lists the actions. **Result** says what you must see. **Criteria** lists the acceptance criteria from section 5.

Common rules for every step:

- Run each Python command with `python -B`.
- Put each temporary file outside the repo, in the scratchpad.
- Create only the files that the step names.
- Do not print a key. Do not commit a key.
- Write one line to the run log after each step: step id, PASS or FAIL, time.

### Phase P0: Setup

### P0-S01 - Create the repo skeleton and the working rules

**Goal.** Give the project one folder per layer and one memory file with the rules.

**Do:**
1. Create CLAUDE.md with these sections: what this is, build and run, working rules, folder map, key definitions, open items.
2. Write the working rules: create only the files asked for; leave no side files; put temporary files outside the repo.
3. Add two more rules: change one definition at a time and show the diff. Flag an ambiguity instead of a guess.
4. Create the folders db, semantics, agent, evals, api, web, tests and docs.
5. Create .gitignore with .env, *.sqlite, logs/, __pycache__/, node_modules/ and web/dist/.

**Result.** CLAUDE.md has a "Working rules" section. The eight folders exist.

**Criteria.** AC-01.

### P0-S02 - Pin every dependency

**Goal.** Make the environment the same on every machine.

**Do:**
1. Write requirements.txt with one package per line and an exact version after `==`.
2. Install the packages.
3. Run `pip check`.

**Result.** The command reports no broken requirements.

**Criteria.** AC-02, AC-03.

### P0-S03 - Keep secrets out of the repo

WARNING: A key in git history stays there after a delete. Scan before each push.

**Goal.** Make sure no key can reach git or a log.

**Do:**
1. Create .env.example with the variable names only.
2. Add the rule to CLAUDE.md: never print or commit .env; redact keys in error text.
3. Run `git check-ignore .env`.
4. Scan the full git history for key patterns.

**Result.** The ignore check prints .env. The scan finds zero hits.

**Criteria.** AC-04.

### P0-S04 - Pin the as-of date as one build setting

**Goal.** Make "today" a setting, so the data and each answer agree.

**Do:**
1. Write AS_OF_DATE in CLAUDE.md.
2. Make the generator, the catalog and the engine read that one value.
3. Search the code for the real clock. Remove each use.

**Result.** One source file holds the date. No file reads the real clock.

**Criteria.** AC-05.

### Phase P1: Data layer

### P1-S01 - Write the schema with its definitions in the header

**Goal.** Define the tables, the allowed values and the business definitions in one file.

**Do:**
1. Write a header comment with one paragraph per business definition.
2. Add one line per rule family and at least three example questions.
3. Make each table STRICT.
4. Add a CHECK list to each status or category column.
5. Add a FOREIGN KEY to each reference column.
6. Use one TEXT timestamp format in UTC.
7. Do not store a derived fact as a column.

**Result.** db/schema.sql exists. The count of STRICT tables equals the count of tables.

**Criteria.** AC-06, AC-07, AC-08.

**Example.** The header defines a candidate for release, a hold and a case to investigate. It says a named person makes the decision. The decision is not a stored column.

### P1-S02 - Write the deterministic data generator

CAUTION: The generator deletes and recreates the database file. Run the catalog build again after it.

**Goal.** Produce the same synthetic data on each run, with known facts planted.

**Do:**
1. Use a random generator with a fixed seed.
2. Set NOW to AS_OF_DATE. Do not read the real clock.
3. Delete and recreate DB_FILE from db/schema.sql.
4. Accept the arguments --rows and --out.
5. Plant at least one record per rule family that triggers the rule, and one that does not.
6. Print the row count of each table and each planted fact.

**Result.** DB_FILE exists. The generator has no call to the real clock.

**Criteria.** AC-09, AC-10.

### P1-S03 - Turn foreign keys on and check integrity

**Goal.** Make each connection enforce references, and show the data is clean.

**Do:**
1. Run `PRAGMA foreign_keys = ON` on each connection.
2. Run `PRAGMA foreign_key_check`.
3. Run `PRAGMA integrity_check`.

**Result.** The first check returns an empty list. The second returns ok.

**Criteria.** AC-11.

### P1-S04 - Verify byte-identical regeneration

**Goal.** Show the generator is deterministic, so evals and CI can trust the data.

**Do:**
1. Build the database twice into the scratchpad.
2. Compute the SHA-256 digest of each file.
3. Compare the two digests.
4. Record the seed, the date and the digest in CLAUDE.md.

**Result.** The two digests are equal. No new file is in the repo.

**Criteria.** AC-12.

**Example.** Two builds of the one-month register give the same digest. A build that writes the real clock into a row gives a different digest. The step stops.

### P1-S05 - Record the reference facts

**Goal.** Write down the planted facts that the golden set and the UI checks will use.

**Do:**
1. Add a "Sample data" section to CLAUDE.md.
2. Write the row counts.
3. Write, for each rule family, the count of records that trigger it.
4. Write the value of KEY_METRIC.
5. Write the SQL that reproduces each fact.

**Result.** The section has one fact per rule family, each with its SQL.

**Criteria.** AC-13.

### Phase P2: Semantic catalog

### P2-S01 - Design the catalog tables

**Goal.** Decide the six meta tables that describe the data for the model and the API.

**Do:**
1. Write semantics/README.md.
2. Describe meta_tables, meta_columns, meta_joins, meta_metrics, meta_glossary and meta_settings.
3. List the columns of each meta table.

**Result.** The README names all six tables.

**Criteria.** AC-14.

### P2-S02 - Build the catalog from the schema

**Goal.** Read types, allowed values and foreign keys from the schema, not from memory.

**Do:**
1. Write semantics/build_catalog.py.
2. Parse db/schema.sql for columns, CHECK lists and foreign keys.
3. Merge the drafted descriptions from one dictionary per table.
4. Write the six meta tables into DB_FILE.
5. Exit with an error when a draft and the schema do not agree.
6. Run the build.

**Result.** meta_columns has one row for each data column.

**Criteria.** AC-15, AC-16.

### P2-S03 - Write every metric and rule family as a SQL fragment

**Goal.** Keep each formula in the catalog once. The engine and the API compose it.

**Do:**
1. Add one meta_metrics row per metric and one per rule family.
2. Give each row an expression, a base table, joins, filters, a time column and notes.
3. Mark a rule whose input column is not in the schema as NOT ASSESSABLE.
4. Give a NOT ASSESSABLE rule no expression.
5. Run the build.

**Result.** No formula is in the agent or the API code. The catalog holds each one.

**Criteria.** AC-17, AC-18.

**Example.** Each of C1 to C7 is one fragment. A control that needs a column the register does not have is NOT ASSESSABLE. It is not a guess.

### P2-S04 - Write the glossary with flags

**Goal.** Give each business term one definition. Flag doubt, PII and gaps.

**Do:**
1. Add meta_glossary rows with term, kind, definition, SQL hint and synonyms.
2. Set is_ambiguous and write a note where two readings exist.
3. Set is_pii on each name and contact column in meta_columns.
4. Keep at least two terms with is_answerable = 0.
5. Keep one vocabulary list in one Python constant.
6. Run the build.

**Result.** Each ambiguous entry has a note. At least one PII column is flagged. At least two terms are not answerable.

**Criteria.** AC-19, AC-20, AC-21.

### P2-S05 - Add the catalog self-checks

**Goal.** Make the build fail loudly when the catalog drifts from the data.

**Do:**
1. Check that each referenced column and metric exists.
2. Run EXPLAIN on each SQL hint and each expression.
3. Check that no synonym belongs to two unflagged terms.
4. Check that each example value is in its CHECK list.
5. Check that meta_joins matches the schema foreign keys.
6. Exit with an error when one check fails.

**Result.** The build exits with code 0. Each hint runs.

**Criteria.** AC-22.

### P2-S06 - Add term lookup with plural and variant handling

**Goal.** Resolve plural words and typed variants to one term.

**Do:**
1. Write find_term(conn, phrase).
2. Match names and synonyms without regard to case.
3. Try again with each word in singular form.
4. Add a LOOKUP_CHECKS list of at least ten phrases.
5. Make the build verify each phrase.
6. Do not add plural synonyms to the glossary.

**Result.** The build prints the lookup check count and exits with code 0.

**Criteria.** AC-23.

### Phase P3: Naive spike

### P3-S01 - Run a naive spike with no context

**Goal.** Show what the model does with no schema, no rules and no guardrails.

**Do:**
1. Write agent/naive_spike.py.
2. Send one hard-coded question about KEY_METRIC with no schema context.
3. Print the reply.
4. Do not open the database. Do not run SQL.

**Result.** The raw reply is on screen. The file has no database call.

**Criteria.** AC-24.

**Example.** Ask "which records in the register can be released?" with no context. The model invents a table. It invents a value threshold. It does its own arithmetic.

### P3-S02 - Record the failure modes

**Goal.** Map each failure mode to the step that will fix it.

**Do:**
1. Add a table "Spike failure modes" to CLAUDE.md.
2. Write one row per failure mode: the mode, an example from the reply, the step id that fixes it.
3. Write at least three rows.
4. Include each reserved action the model offered.

**Result.** The table has three or more rows. Each row has a step id.

**Criteria.** AC-25, AC-26.

### Phase P4: Golden set and scoring

### P4-S01 - Generate the golden set from reference SQL

**Goal.** Make expected answers come from SQL that runs, never from typing.

**Do:**
1. Write evals/make_golden_set.py.
2. Give each question an id, the text, the reference SQL and a note with the planted fact.
3. Add order_matters, tolerance, alternatives or expect_refusal where needed.
4. Cover easy lookups, date ranges, joins, zero-row edge cases and one question per rule family.
5. Add at least two refusal questions.
6. Run the reference SQL and write evals/golden_set.yaml.
7. Run the generator again into the scratchpad and compare the files.

**Result.** The two files are the same.

**Criteria.** AC-27.

### P4-S02 - Add the self-test that needs no API key

**Goal.** Show the golden set agrees with the data before any model is called.

**Do:**
1. Write evals/run_evals.py.
2. Add --self-test, --golden and --json.
3. Exit with code 2 when the provider cannot be reached.
4. Run the self-test with no key in the environment.

**Result.** The score is N of N, where N is the question count.

**Criteria.** AC-28.

### P4-S03 - Write the scoring rules

**Goal.** Score what matters, and accept what is legitimately different.

**Do:**
1. Compare rows without regard to order, unless order_matters is set.
2. Apply the numeric tolerance.
3. Accept extra columns when a subset matches.
4. Accept each listed alternative.
5. Pass a refusal question only on a refusal.
6. Use the statuses pass, wrong_result, sql_error, unsafe and no_sql.
7. Run the scoring tests.

**Result.** The tests pass. A correct answer to a refusal question scores as a fail.

**Criteria.** AC-29, AC-30, AC-31.

### P4-S04 - Run a trap check with wrong SQL

**Goal.** Show the scorer catches wrong answers, not only right ones.

**Do:**
1. Write a scratchpad script that feeds wrong SQL to the scorer.
2. Use a wrong filter, a wrong join and a count in place of a rate.
3. Print caught and total.
4. Explain each miss in CLAUDE.md as a limit of the golden set.

**Result.** The counts are on screen. Each miss has an explanation.

**Criteria.** AC-32.

### Phase P5: Engine and LLM assist

### P5-S01 - Build the deterministic engine

WARNING: Do not add a value threshold. A threshold invites a split of one record into smaller parts.

**Goal.** Run each rule on each record in code, and emit only the allowed words.

**Do:**
1. Write agent/engine.py.
2. Read the rule fragments from meta_metrics.
3. Write one result row per record and per rule: record id, rule id, result, evidence values.
4. Give a NOT ASSESSABLE rule that status and no result.
5. Combine the results into one recommendation per record from DECISION_VOCABULARY only.
6. Do all arithmetic in Python or SQL.
7. Run the engine tests.

**Result.** The result count equals records times rules. The code has no threshold.

**Criteria.** AC-33, AC-34, AC-35, AC-36.

**Example.** Each record in the one-month register gets C1 to C7. The smallest record gets the same rules as the largest. The output words are RELEASE-CANDIDATE, HOLD and INVESTIGATE. A rule the data cannot support is NOT ASSESSABLE.

### P5-S02 - Resolve terms and refuse before any API call

This step runs only when LLM_QUERY_PATH is true.

**Goal.** Stop a question the data cannot answer before it costs a call.

**Do:**
1. Write translate(question) in agent/nl2sql.py.
2. Resolve phrases of one to four words, longest first, with find_term.
3. Return a refusal for a term with is_answerable = 0.
4. Make no model call for a refusal.
5. Run the refusal tests.

**Result.** The tests pass. The fake model counts zero calls.

**Criteria.** AC-37.

### P5-S03 - Build the prompt from the catalog only

This step runs only when LLM_QUERY_PATH is true.

**Goal.** Keep the schema out of the code, so a catalog change is the only change.

**Do:**
1. Write build_context(conn).
2. Render the rules, then meta_tables, meta_columns, meta_joins, meta_metrics and meta_glossary, then the terms found.
3. Set temperature to 0.
4. Write an "-- assumption:" line in the SQL for an ambiguous term.
5. Read the as-of date from meta_settings.
6. Search the agent source for the fact table name.

**Result.** The search finds zero matches.

**Criteria.** AC-38, AC-39.

### P5-S04 - Add the hard SQL lint

This step runs only when LLM_QUERY_PATH is true.

**Goal.** Block SQL that runs but is certainly wrong, after one repair.

**Do:**
1. Write lint_sql.
2. Flag SQL that EXPLAIN rejects.
3. Flag an unknown date modifier.
4. Flag two child tables in one aggregate query without a direct foreign key.
5. Flag a parent filter inside a LEFT JOIN ON clause.
6. Send the SQL and the finding back to the model once.
7. Mark the SQL unsafe when it is still wrong.
8. Run the lint tests.

**Result.** The tests pass. The golden reference SQL lints clean.

**Criteria.** AC-40.

### P5-S05 - Add the soft question checks

This step runs only when LLM_QUERY_PATH is true.

**Goal.** Repair SQL that does not match the question, but never block on a doubt.

**Do:**
1. Write lint_question.
2. Flag a status filter nobody asked for.
3. Flag a list question answered with one aggregate.
4. Flag a share of the grand total where a proportion was asked.
5. Flag an inverted percentage.
6. Flag a window that starts at the as-of date in place of the first of the period.
7. Make at most one repair call. Never set unsafe.
8. Run the soft lint tests.

**Result.** The tests pass. One test asserts at most one repair call.

**Criteria.** AC-41.

### P5-S06 - Add the execution guardrails

**Goal.** Make it impossible for any SQL to write, to leak PII or to run away.

**Do:**
1. Accept exactly one SELECT or WITH statement.
2. Reject write and admin keywords.
3. Add LIMIT 1000 when it is missing.
4. Open the database read-only.
5. Install an authorizer allow-list: SELECT, READ, FUNCTION, RECURSIVE.
6. Deny each is_pii column and load_extension in the authorizer.
7. Set a 1 MB value limit, a 100 KB SQL limit, no ATTACH and a heap limit.
8. Add a 5 second timeout and a row cap with fetchmany.
9. Run the guardrail and security tests.

**Result.** The tests pass, including SELECT * on a table with PII.

**Criteria.** AC-42, AC-43, AC-44.

### P5-S07 - Add the provider layer

**Goal.** Call any model through one function, with a model allow-list and safe errors.

**Do:**
1. Write complete(system, user, provider, model) in agent/llm.py.
2. Return text, provider, model, latency and token counts.
3. Write allowed_models() from a constant and an environment list.
4. Use the fallback provider only when none was requested.
5. Retry HTTP 429 up to three times.
6. Remove key fragments from error text with redact().
7. Raise one error type for each failure.
8. Run the provider tests.

**Result.** The tests pass with mocked clients.

**Criteria.** AC-45, AC-46.

### P5-S08 - Fix the output contract

WARNING: The system never makes the decision. A reserved action in model text is an error, not a result.

**Goal.** Give the person a decision-ready record, and never let the system decide.

**Do:**
1. Define the decision record: record id, rule results, evidence values, recommendation, decided_by, decided_at.
2. Leave decided_by empty until a person fills it.
3. Lint each narrative: each decision word is in DECISION_VOCABULARY.
4. Lint each narrative: each number equals an engine value.
5. Reject each text that uses a RESERVED_ACTIONS verb as an action.
6. Run the contract tests.

**Result.** The tests pass. A reserved action in model text is rejected.

**Criteria.** AC-47, AC-48.

**Example.** The register that goes to the named person has the seven rule results, the evidence and a recommendation per record. The system never writes the word for the reserved action.

### Phase P6: Live evals and probe rounds

### P6-S01 - Run the live eval at least twice

This step runs only when LLM_QUERY_PATH is true.

**Goal.** Get a score you can trust. The model is not deterministic, even at temperature 0.

**Do:**
1. Run the eval with --json and keep the report in the scratchpad.
2. Run it again.
3. Record both scores, the provider, the model, the date and each failed id in CLAUDE.md.

**Result.** Two reports exist. CLAUDE.md shows both scores.

**Criteria.** AC-49.

### P6-S02 - Run a probe round and add failures to the set first

This step runs only when LLM_QUERY_PATH is true.

**Goal.** Grow the golden set from real misses before any fix, so the fix is measured.

**Do:**
1. Write new questions with separate reference SQL in the scratchpad.
2. Run the eval on them.
3. Add each failed question, its SQL and a note to the generator.
4. Regenerate the golden set.

**Result.** The golden set grew by the number of failures.

**Criteria.** AC-50.

### P6-S03 - Fix narrowly and re-run the whole set

This step runs only when LLM_QUERY_PATH is true.

**Goal.** Fix one cause at a time, and show nothing else broke.

**Do:**
1. Prefer a catalog note or a clause on an existing prompt rule.
2. Avoid a new standalone rule.
3. Change one entry. Show the before and after. Then roll it out.
4. Rebuild the catalog. Run the self-test. Run the live eval.
5. Compare the report with the last one.

**Result.** The self-test is 100 percent. The live score is equal or higher. No new id failed.

**Criteria.** AC-51.

### P6-S04 - Record the lesson

**Goal.** Keep the cause, the change and the scores where the next person reads.

**Do:**
1. Write one entry per fix in the Evals section of CLAUDE.md.
2. Give the question ids, the root cause, the entry changed, the score before and after.
3. Keep the standing lesson: prompt rules outrank catalog notes.
4. Keep the second lesson: a clause on an existing rule is safer than a new rule.

**Result.** The Evals section has one entry per fix with before and after scores.

**Criteria.** AC-52.

### Phase P7: API

### P7-S01 - Build a thin API that composes catalog fragments

**Goal.** Serve numbers from the catalog, through a fresh read-only connection per request.

**Do:**
1. Write api/main.py with /health, /api/overview, /api/kpis, /api/tables/{name}, /api/results, /api/sql, /api/reconcile and /api/catalog/{section}.
2. Add /api/ask when LLM_QUERY_PATH is true.
3. Accept dataset=default or large on each route.
4. Open one read-only connection per request, safe across threads.
5. Compose each KPI from meta_metrics rows in api/services.py.
6. Allow-list the explorer column names. Bind each value.
7. Run the API tests.

**Result.** The tests pass. The API code has no formula.

**Criteria.** AC-53, AC-54.

### P7-S02 - Add the API key and the rate limit

**Goal.** Gate each /api route, and limit by client, not by the key the client sends.

**Do:**
1. Require X-API-Key on /api/* when APP_API_KEY is set.
2. Compare the key as bytes in constant time.
3. Limit calls per client IP and per bucket: ask, sql, evals, feedback, decision.
4. Store the hits in the state store.
5. Run the key and rate-limit tests.

**Result.** A test that rotates the API key is still limited.

**Criteria.** AC-55, AC-56.

### P7-S03 - Add the audit log

**Goal.** Keep one line per call, so a reviewer can see who asked what and what ran.

**Do:**
1. Write logs/audit.jsonl with request id, client, route, question or SQL hash, provider, model, row count, status and duration.
2. Redact keys.
3. Make sure logs/ is ignored by git.
4. Run the audit test.

**Result.** git ignores the log file. The test passes.

**Criteria.** AC-57.

### P7-S04 - Add the model allow-list, job cap and state store

**Goal.** Stop cost abuse and runaway jobs, and keep limits across processes.

**Do:**
1. Write api/state.py as a SQLite store in WAL mode.
2. Store rate-limit hits and background jobs.
3. Mark a running job older than 30 minutes as failed.
4. Reject a model that is not in allowed_models() with a 4xx status.
5. Cap running jobs at 2, counted from the store.
6. Run the state and security tests.

**Result.** The tests pass.

**Criteria.** AC-58.

### P7-S05 - Add the human decision endpoint

**Goal.** Record the decision of a named person, and reject anything else.

**Do:**
1. Write POST /api/decision with record id, decision, decided_by and note.
2. Return 422 when the name is empty.
3. Return 422 when the decision word is not in DECISION_VOCABULARY.
4. Store the decision with a snapshot of the evidence.
5. Make sure no endpoint does a RESERVED_ACTIONS action.
6. Run the decision tests.

**Result.** 422 without a name. 422 for a word outside the vocabulary. 200 otherwise.

**Criteria.** AC-59.

**Example.** The named reviewer posts HOLD for a record with a note. A post with no name is rejected. A post with the reserved word is rejected.

### Phase P8: UI

### P8-S01 - Build the UI against the API only

**Goal.** Keep the browser away from the database and the model.

**Do:**
1. Create a React and TypeScript app in web/ with hash routes.
2. Call the API on the same origin only.
3. Serve the built app from the API at /web/.
4. Add the pages Home, Results or Ask, Dashboard, Explorer, Record detail, Catalog, Evals and Data check.
5. Install, lint and build.

**Result.** web/dist exists. package.json has no database driver.

**Criteria.** AC-60.

### P8-S02 - Show the evidence beside every answer

**Goal.** Let the person check the SQL or the rule result, not trust a sentence.

**Do:**
1. Show the SQL that ran, or the rule results and evidence values, with each answer.
2. Add a copy button.
3. Show each assumption as a labelled line.
4. Run the evidence end-to-end test.

**Result.** The test finds the evidence block on each answer.

**Criteria.** AC-61.

### P8-S03 - Add the reconciliation page

**Goal.** Compare each number the UI shows with SQL written separately from the catalog.

**Do:**
1. Write DIRECT_CHECKS in api/services.py, one per number on screen.
2. Write that SQL from the schema header definitions, not from meta_metrics.
3. Return match per check from /api/reconcile.
4. Add a Data check page with UI value, direct value and match.
5. Call the endpoint on both datasets.

**Result.** N of N checks match on both datasets.

**Criteria.** AC-62, AC-63.

### P8-S04 - Add feedback and the decision controls

**Goal.** Capture what people think, and keep each reserved action off the screen.

**Do:**
1. Add thumbs up and down per answer, posted to /api/feedback.
2. Offer only DECISION_VOCABULARY in the decision controls.
3. Require the name of the person.
4. Post the decision to /api/decision.
5. Make sure no button, link or menu item has a RESERVED_ACTIONS verb.
6. Run the feedback, decision and reserved end-to-end tests.

**Result.** Feedback is stored. The decision is posted. Zero controls have a reserved verb.

**Criteria.** AC-64, AC-65.

### Phase P9: Tests

### P9-S01 - Make the test suite run with no key and no side files

**Goal.** Let anyone run the tests anywhere, and leave the repo clean.

**Do:**
1. Write tests/conftest.py.
2. Build a temporary database in a folder outside the repo.
3. Add a fake model that returns scripted SQL and counts calls.
4. Remove each provider key from the environment for the session.
5. Run the full suite with no key.
6. Run `git status --porcelain --untracked-files=all`.

**Result.** All tests pass. git status shows nothing new.

**Criteria.** AC-66, AC-67.

### P9-S02 - Add a regression test for every bug and finding

**Goal.** Make each fix stay fixed.

**Do:**
1. Write one test per bug or finding listed in CLAUDE.md.
2. Name the finding in a comment in the test.
3. Make sure the test fails on the code before the fix.
4. Add one test that runs lint_sql on each golden reference SQL.
5. Run the suite.

**Result.** The finding count equals the tagged test count. The golden lint test passes.

**Criteria.** AC-68, AC-69.

### P9-S03 - Add end-to-end browser tests

**Goal.** Show the pages work against a real API started by the test run.

**Do:**
1. Write a Playwright suite in web/e2e.
2. Start the API on its own port from the suite.
3. Load each page. Ask one question or open one result.
4. Check the reconciliation page.
5. Run the suite.

**Result.** All checks pass.

**Criteria.** AC-70.

### Phase P10: Security hardening

### P10-S01 - Write the attack probe list

**Goal.** Try to break the system before anyone else does.

**Do:**
1. Write a probe list in the scratchpad.
2. Add at least one probe per class.
3. Use these eight classes: SQL injection, prompt or key extraction, PII read, server path leak.
4. Add these four: size bomb, rate-limit bypass, model abuse, key echo.

**Result.** The list has eight classes.

**Criteria.** AC-71.

### P10-S02 - Run the probes, fix, test, re-run

**Goal.** Turn each finding into a fix and a test.

**Do:**
1. Run the probes against the local API.
2. Fix each finding.
3. Add one test per finding in tests/test_security.py.
4. Run the probes again until the count is zero.
5. Record finding, fix and test name in CLAUDE.md.

**Result.** The probe run reports zero findings. All security tests pass.

**Criteria.** AC-72.

### P10-S03 - Run the domain-rule probes

**Goal.** Show the business rules hold under pressure, not only the technical ones.

**Do:**
1. Ask the system to do each reserved action.
2. Ask for a decision word outside the vocabulary.
3. Split one record into two smaller records. Compare the rule results.
4. Ask for a rule to be skipped below a value.
5. Add the four tests to tests/test_engine.py.

**Result.** Zero findings. The tests pass.

**Criteria.** AC-73, AC-74.

**Example.** One record is split into two parts. Each part gets exactly the same C1 to C7 results as the whole record.

### P10-S04 - Write down the known limits and the exposure checklist

**Goal.** Say what is not protected, so nobody assumes it is.

**Do:**
1. Write docs/security.md.
2. Add a table: threat, protection, where.
3. Add a section "Known limits (accepted)".
4. Add a numbered "Checklist before exposing the app".

**Result.** The file has both sections.

**Criteria.** AC-75.

### Phase P11: CI, docs and handover

### P11-S01 - Add CI that regenerates and self-tests without secrets

**Goal.** Make each push show the data, the catalog and the tests still agree.

**Do:**
1. Write .github/workflows/ci.yml.
2. Python job: install, pip check, seed and catalog per size, regenerate golden sets, `git diff --exit-code`, self-tests, pytest.
3. Web job: install, lint, build, start the API, check /web/ and /api/reconcile.
4. Use no secret in the workflow.

**Result.** The diff exits with code 0. The workflow has no secrets key.

**Criteria.** AC-76, AC-77.

### P11-S02 - Update the documentation with the code

**Goal.** Keep CLAUDE.md and the guide true on the day of handover.

**Do:**
1. Update the build and run commands, the folder map, the definitions and the open items.
2. Take each count from a fresh run on this day.
3. Write one chapter per layer in docs/.
4. Commit the docs with the last code change.

**Result.** The last commit touches CLAUDE.md or docs/.

**Criteria.** AC-78.

### P11-S03 - Scan for secrets and names before any push

WARNING: A public repo shows each commit to everyone. Scan first. Push second.

**Goal.** Keep keys, client names and employer names out of a shared repo.

**Do:**
1. Scan the staged diff for key patterns.
2. Scan the staged diff for each client or employer name.

**Result.** Zero hits.

**Criteria.** AC-79.

### P11-S04 - Hand over with a run log and a named sign-off

**Goal.** Give the named person a complete record and the final word.

**Do:**
1. Write docs/handover.md.
2. Add a table with step id, PASS or FAIL and time for all 53 steps.
3. Add a table with each criterion id and its evidence.
4. Add the sign-off line: name, role, date, and the sentence "The system prepares and recommends. I decide."
5. Ask the named person to sign.

**Result.** 53 PASS rows. 80 criterion rows. One signed line.

**Criteria.** AC-80.

## 5. Acceptance criteria

Each criterion has one primary step. The pass condition is measurable. A build is accepted when all 80 pass.

| AC id | Phase | Step | Criterion | Pass condition |
|---|---|---|---|---|
| AC-01 | P0 | P0-S01 | Keep the working rules in CLAUDE.md. | The file has a "Working rules" section with the four rules. |
| AC-02 | P0 | P0-S02 | Pin each dependency to one exact version. | Each non-comment line in requirements.txt has `==` and a version. |
| AC-03 | P0 | P0-S02 | Make sure the installed packages agree. | `pip check` exits with code 0. |
| AC-04 | P0 | P0-S03 | Keep each key out of git. | `.env` is ignored, and a history scan for key patterns finds zero hits. |
| AC-05 | P0 | P0-S04 | Keep the as-of date in one setting. | One source file holds the date, and no file reads the real clock. |
| AC-06 | P1 | P1-S01 | Make each table STRICT. | The count of CREATE TABLE equals the count of STRICT. |
| AC-07 | P1 | P1-S01 | Give each status or category column a CHECK list. | Each such column has a CHECK clause in db/schema.sql. |
| AC-08 | P1 | P1-S01 | Write each business definition in the schema header. | The header has one paragraph per definition and three or more example questions. |
| AC-09 | P1 | P1-S02 | Make the generator deterministic. | The seed is fixed, NOW equals AS_OF_DATE, and the file has no real-clock call. |
| AC-10 | P1 | P1-S02 | Do not store a derived fact as a column. | No column in the schema holds a value that a catalog fragment computes. |
| AC-11 | P1 | P1-S03 | Keep the data clean under foreign keys. | foreign_key_check returns an empty list, and integrity_check returns ok. |
| AC-12 | P1 | P1-S04 | Make two builds give the same file hash. | Both SHA-256 digests are equal. |
| AC-13 | P1 | P1-S05 | Record one planted fact per rule family. | CLAUDE.md lists each fact with the SQL that reproduces it. |
| AC-14 | P2 | P2-S01 | Design the six catalog tables. | semantics/README.md names all six meta tables and their columns. |
| AC-15 | P2 | P2-S02 | Describe each data column in the catalog. | The meta_columns row count equals the data column count. |
| AC-16 | P2 | P2-S02 | Read types, allowed values and keys from the schema. | The build parses db/schema.sql, and a draft that does not match stops the build. |
| AC-17 | P2 | P2-S03 | Keep each formula in the catalog only. | A search of agent and api code for formula patterns finds zero matches. |
| AC-18 | P2 | P2-S03 | List each rule the data cannot assess as NOT ASSESSABLE. | Each rule with a missing input column has that status and no expression. |
| AC-19 | P2 | P2-S04 | Flag each ambiguous entry with a note. | No row has is_ambiguous = 1 and an empty note. |
| AC-20 | P2 | P2-S04 | Flag each PII column. | Each name and contact column has is_pii = 1. |
| AC-21 | P2 | P2-S04 | Keep at least two terms the data cannot answer. | The count of is_answerable = 0 terms is 2 or more. |
| AC-22 | P2 | P2-S05 | Make the catalog build fail on drift. | Each hint runs under EXPLAIN, no synonym is duplicated, and the build exits with code 0. |
| AC-23 | P2 | P2-S06 | Resolve plural and variant phrases. | Each phrase in LOOKUP_CHECKS resolves to the expected term. |
| AC-24 | P3 | P3-S01 | Keep the spike free of context and of database access. | The spike file has no schema text and no database call. |
| AC-25 | P3 | P3-S02 | Record three or more failure modes. | The table has 3 or more rows. |
| AC-26 | P3 | P3-S02 | Map each failure mode to a fix. | Each row names a step id that exists in the playbook. |
| AC-27 | P4 | P4-S01 | Generate expected rows from reference SQL. | Two generator runs give byte-identical files. |
| AC-28 | P4 | P4-S02 | Pass the self-test with no API key. | The score is N of N with each key variable unset. |
| AC-29 | P4 | P4-S03 | Score without regard to order, with tolerance. | Tests for reordered rows and rounded numbers pass. |
| AC-30 | P4 | P4-S03 | Pass a refusal question only on a refusal. | A correct answer to a refusal question scores as a fail. This applies when the query path is enabled. |
| AC-31 | P4 | P4-S03 | Separate a provider failure from a wrong answer. | A provider failure exits with code 2 and is not counted. |
| AC-32 | P4 | P4-S04 | Catch wrong SQL with the scorer. | The trap check reports caught of total, and each miss has a written reason. |
| AC-33 | P5 | P5-S01 | Run each rule on each record. | The result row count equals records times rules. |
| AC-34 | P5 | P5-S01 | Do all arithmetic in code. | Each number in model text equals an engine value, and a test asserts it. |
| AC-35 | P5 | P5-S01 | Use only the decision vocabulary. | The lint rejects each word outside DECISION_VOCABULARY and NOT ASSESSABLE. |
| AC-36 | P5 | P5-S01 | Do not exempt a record from a rule by value. | The code has no threshold key, and the smallest and the largest record get all rules. |
| AC-37 | P5 | P5-S02 | Refuse before the API call. | A refusal makes zero model calls. This applies when the query path is enabled. |
| AC-38 | P5 | P5-S03 | Build the prompt from the catalog only. | A search of the agent source for the fact table name finds zero matches. |
| AC-39 | P5 | P5-S03 | Make the model call deterministic and explicit. | Temperature is 0, and an ambiguous term gives an assumption line. |
| AC-40 | P5 | P5-S04 | Block SQL that is certainly wrong. | A lint finding gets one repair, and a repeat finding is marked unsafe. |
| AC-41 | P5 | P5-S05 | Repair on doubt, never block. | A soft finding makes at most one repair call and never sets unsafe. |
| AC-42 | P5 | P5-S06 | Accept one read-only SELECT only. | A second statement, a write keyword or a write attempt is rejected. |
| AC-43 | P5 | P5-S06 | Block each PII column by authorizer. | SELECT * on a table with PII fails. |
| AC-44 | P5 | P5-S06 | Cap rows, time and size. | LIMIT is added, the row cap holds, a 5 second query stops, and a 400 MB value fails. |
| AC-45 | P5 | P5-S07 | Call each model through one function with an allow-list. | A model not in allowed_models() is rejected. |
| AC-46 | P5 | P5-S07 | Retry on 429 and redact keys. | A 429 is retried three times, and no error text has a key fragment. |
| AC-47 | P5 | P5-S08 | Give the person a record with evidence and a name field. | Each decision record has rule results, evidence and an empty decided_by. |
| AC-48 | P5 | P5-S08 | Never emit a reserved action. | The count of reserved verbs over the golden set and the probes is zero. |
| AC-49 | P6 | P6-S01 | Trust a live score only after two runs. | CLAUDE.md shows two scores with provider, model and date. This applies when the query path is enabled. |
| AC-50 | P6 | P6-S02 | Add a failed probe to the golden set before the fix. | The golden set grows by the failure count before any catalog change. |
| AC-51 | P6 | P6-S03 | Re-run the whole set after each fix. | The self-test is 100 percent, and the live score has no new failed id. |
| AC-52 | P6 | P6-S04 | Record cause, change and scores for each fix. | Each Evals entry has the ids, the cause, the entry changed, and before and after scores. |
| AC-53 | P7 | P7-S01 | Compose each KPI from catalog fragments. | A search of the API code for formula patterns finds zero matches. |
| AC-54 | P7 | P7-S01 | Open one read-only connection per request. | A test that uses the connection across threads passes. |
| AC-55 | P7 | P7-S02 | Require the API key on each /api route. | A request without the header gets 401 when APP_API_KEY is set. |
| AC-56 | P7 | P7-S02 | Limit by client IP, per bucket. | A test that rotates the key is still limited. |
| AC-57 | P7 | P7-S03 | Log each call, with keys redacted. | logs/audit.jsonl gets one line per call, and git ignores it. |
| AC-58 | P7 | P7-S04 | Reject unknown models and cap jobs. | An unknown model gets a 4xx, and a third running job is refused. |
| AC-59 | P7 | P7-S05 | Record each decision with a named person. | The API returns 422 without a name or with a word outside the vocabulary. |
| AC-60 | P8 | P8-S01 | Keep the UI on the API only. | package.json has no database driver, and each call goes to the same origin. |
| AC-61 | P8 | P8-S02 | Show evidence with each answer. | The end-to-end test finds the evidence block on each answer. |
| AC-62 | P8 | P8-S03 | Make each number on screen equal its independent SQL value. | /api/reconcile reports N of N matches on both datasets. |
| AC-63 | P8 | P8-S03 | Write the check SQL apart from the catalog. | DIRECT_CHECKS does not import or read meta_metrics. |
| AC-64 | P8 | P8-S04 | Capture feedback through the API. | A thumbs click creates one feedback row. |
| AC-65 | P8 | P8-S04 | Keep each reserved action off the screen. | The end-to-end test finds zero controls with a reserved verb. |
| AC-66 | P9 | P9-S01 | Run the tests with no API key. | The suite exits with code 0 with each key variable unset. |
| AC-67 | P9 | P9-S01 | Keep the test database outside the repo. | git status is unchanged after the run. |
| AC-68 | P9 | P9-S02 | Give each bug and finding one regression test. | The finding count equals the tagged test count. |
| AC-69 | P9 | P9-S02 | Lint each golden reference SQL. | The golden lint test passes. |
| AC-70 | P9 | P9-S03 | Run end-to-end tests against a self-started API. | The suite starts the API on its own port and exits with code 0. |
| AC-71 | P10 | P10-S01 | Cover eight attack classes in the probe list. | The list has 8 or more class headings. |
| AC-72 | P10 | P10-S02 | Turn each finding into a fix and a test. | The probe run reports zero findings, and all security tests pass. |
| AC-73 | P10 | P10-S03 | Refuse each reserved action under pressure. | Each reserved-action probe is refused. |
| AC-74 | P10 | P10-S03 | Give a split record the same rule results. | The two parts get the same rule results as the whole record. |
| AC-75 | P10 | P10-S04 | Write down the known limits. | docs/security.md has "Known limits" and "Checklist before". |
| AC-76 | P11 | P11-S01 | Regenerate artefacts byte-identical in CI. | `git diff --exit-code` returns 0 after regeneration. |
| AC-77 | P11 | P11-S01 | Run CI with no secret. | The workflow has no secrets reference, and the self-tests and pytest run in it. |
| AC-78 | P11 | P11-S02 | Update docs with the code. | The last commit touches CLAUDE.md or docs/. |
| AC-79 | P11 | P11-S03 | Find zero secrets or names before a push. | The staged-diff scan prints 0. |
| AC-80 | P11 | P11-S04 | Hand over with a full run log and a signed line. | docs/handover.md has 53 PASS rows, 80 criterion rows and a named sign-off. |

## 6. Checks before a hand-over

Do these checks on the day of hand-over. Record the result of each check in docs/handover.md.

1. Run the data build, the catalog build and the self-test. Make sure each exits with code 0.
2. Run the full test suite with no API key. Make sure it exits with code 0.
3. Open the Data check page. Make sure N of N checks match.
4. Run the secret scan on the full diff. Make sure it prints 0.
5. Read the 80 criteria. Mark each one PASS or FAIL with its evidence.
6. Give the hand-over file to the named person. Ask for the signed line.

The build is complete when all 80 criteria are PASS and the line is signed.
