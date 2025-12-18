from pyteal import *
from contracts.presale.confio_presale import confio_presale

# Compile the contract
approval_program = compileTeal(confio_presale(), mode=Mode.Application, version=6)

# Save to file
with open("contracts/presale/debug_approval.teal", "w") as f:
    f.write(approval_program)

print("Compiled to contracts/presale/debug_approval.teal")
print(f"Total lines: {len(approval_program.splitlines())}")

# Try to print lines around PC 1104 if possible?
# PC is byte offset, not line number.
# But in uncompressed TEAL, line numbers roughly correlate if comments are included.
# Actually, I need to know the mapping.
# For now, I'll just dump the file.
