# Example API Test

## Setup
Navigate to https://api.example.com

## Test: GET Users Endpoint

### Description
Verify that the GET /api/users endpoint returns a valid response with proper status code and data structure.

### Steps

1. **Send GET Request**
   - Send GET request to `/api/users`
   - Set header `Accept: application/json`

2. **Verify Response Status**
   - Assert status code equals `200`
   - Assert status message contains "OK"

3. **Verify Response Headers**
   - Assert header `Content-Type` contains `application/json`

4. **Verify Response Body**
   - Assert response body is an array
   - Assert each user object contains required fields:
     - `id` (number/string)
     - `name` (string)
     - `email` (string)

### Expected Result
The API returns a 200 status code with a valid JSON array of user objects containing id, name, and email fields.

---

## Test: POST Create User

### Description
Verify that a new user can be created via POST request with proper validation.

### Steps

1. **Send POST Request**
   - Send POST request to `/api/users`
   - Set header `Content-Type: application/json`
   - Send body:
     ```json
     {
       "name": "Test User",
       "email": "test@example.com",
       "role": "user"
     }
     ```

2. **Verify Response Status**
   - Assert status code equals `201`
   - Assert status message contains "Created"

3. **Verify Response Body**
   - Assert response contains created user object
   - Assert `id` field is present and not null
   - Assert `name` equals "Test User"
   - Assert `email` equals "test@example.com"

### Expected Result
The API returns 201 status with the created user object including a generated ID.

---

## Test: PUT Update User

### Description
Verify that an existing user can be updated via PUT request.

### Steps

1. **Send PUT Request**
   - Send PUT request to `/api/users/1`
   - Set header `Content-Type: application/json`
   - Send body:
     ```json
     {
       "name": "Updated Name",
       "email": "updated@example.com"
     }
     ```

2. **Verify Response Status**
   - Assert status code equals `200`

3. **Verify Update**
   - Assert response body `name` equals "Updated Name"
   - Assert response body `email` equals "updated@example.com"

### Expected Result
The API returns 200 status with the updated user object reflecting the changes.

---

## Test: DELETE User

### Description
Verify that a user can be deleted via DELETE request.

### Steps

1. **Send DELETE Request**
   - Send DELETE request to `/api/users/1`

2. **Verify Response Status**
   - Assert status code equals `204` or `200`

3. **Verify Deletion**
   - Send GET request to `/api/users/1`
   - Assert status code equals `404`

### Expected Result
The API returns 204/200 status and subsequent GET requests return 404 for the deleted user.

---

## Test: Error Handling - Invalid Data

### Description
Verify API handles invalid input data properly with appropriate error responses.

### Steps

1. **Send POST with Invalid Email**
   - Send POST request to `/api/users`
   - Send body:
     ```json
     {
       "name": "Test",
       "email": "invalid-email",
       "role": "user"
     }
     ```

2. **Verify Error Response**
   - Assert status code equals `400`
   - Assert response body contains error message
   - Assert response body contains validation details

### Expected Result
The API returns 400 status with a descriptive error message indicating validation failure.

---

## Test: Authentication/Authorization

### Description
Verify that protected endpoints properly authenticate and authorize requests.

### Steps

1. **Request Without Auth**
   - Send GET request to `/api/users/profile`
   - Do not include authorization header

2. **Verify Unauthorized Response**
   - Assert status code equals `401`
   - Assert response contains error indicating authentication required

3. **Request With Valid Token**
   - Send GET request to `/api/users/profile`
   - Set header `Authorization: Bearer valid-token-here`

4. **Verify Success Response**
   - Assert status code equals `200`
   - Assert response contains user profile data

### Expected Result
The API correctly blocks unauthenticated requests with 401 and allows authenticated requests with valid tokens.