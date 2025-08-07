import json
from graphene import Schema
from config.schema import schema

query = """
mutation Web3AuthLogin(
  $provider: String\!
  $web3AuthId: String\!
  $email: String
  $firstName: String
  $lastName: String
  $algorandAddress: String
  $idToken: String
) {
  web3AuthLogin(
    provider: $provider
    web3AuthId: $web3AuthId
    email: $email
    firstName: $firstName
    lastName: $lastName
    algorandAddress: $algorandAddress
    idToken: $idToken
  ) {
    success
    error
    accessToken
    refreshToken
    user {
      id
      email
      algorandAddress
    }
  }
}
"""

variables = {
    "provider": "google",
    "web3AuthId": "test_user_123456",
    "email": "test@example.com",
    "firstName": "Test",
    "lastName": "User",
    "algorandAddress": "ABCD1234EFGH5678IJKL9012MNOP3456QRST7890UVWX1234YZAB5678",
    "idToken": "test_id_token"
}

result = schema.execute(query, variables=variables)

print("GraphQL Result:")
print("Errors:", result.errors)
print("Data:")
if result.data:
    print(json.dumps(result.data, indent=2))
else:
    print("No data returned")
