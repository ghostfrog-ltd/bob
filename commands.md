<!-- commands.md -->
# 1) Just inspect what the meta-layer sees
python3 -m bob.meta analyse --limit 200

# 2) Generate tickets (JSON files in data/meta/tickets/)
python3 -m bob.meta tickets --count 5

# 3.a) Full flow: tickets + queue items for Bob/Chad
python3 -m bob.meta self_improve --count 3

# 3.b) (create tickets + Bob/Chad execute them)
python3 -m bob.meta self_cycle --count 3   

# 4) (teach bob a rule)
python3 -m bob.meta teach_rule "<rule text>"

python3 -m bob.meta teach_rule "When planning self-improvement codemods, avoid planning edits for files that do not exist yet, unless you first create them with create_or_overwrite_file."

# 5) Repair and retry
python3 -m bob.meta repair_then_retry
