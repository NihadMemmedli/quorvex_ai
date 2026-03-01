# Test: User CRUD API

## Type: API
## Base URL: https://api.example.com
## Auth: Bearer {{API_TOKEN}}

## Description
End-to-end test for the User CRUD API: create, read, update, and delete a user resource.

## Steps
1. POST /users with body {"name": "Test User", "email": "test@example.com"}
2. Verify response status is 201
3. Verify response body has "id" field
4. Verify response body.name equals "Test User"
5. Store response.body.id as $userId
6. GET /users/$userId
7. Verify response status is 200
8. Verify response body.name equals "Test User"
9. Verify response body.email equals "test@example.com"
10. PUT /users/$userId with body {"name": "Updated User"}
11. Verify response status is 200
12. Verify response body.name equals "Updated User"
13. DELETE /users/$userId
14. Verify response status is 204
15. GET /users/$userId
16. Verify response status is 404

## Expected Outcome
- User is created with 201 status
- User can be retrieved by ID
- User can be updated
- User can be deleted
- Deleted user returns 404
