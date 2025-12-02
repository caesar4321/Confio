from pyteal import *

def test_compile():
    program = Seq(
        Pop(Txn.accounts[0]),
        Pop(Txn.accounts[1]),
        Approve()
    )
    compiled = compileTeal(program, mode=Mode.Application, version=8)
    print(compiled)

if __name__ == "__main__":
    test_compile()
