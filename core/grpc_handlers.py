from core.tokens import AuthenticationError, validate_access_token
from core.grpc import auth_pb2, auth_pb2_grpc


class AuthServicer(auth_pb2_grpc.AuthServiceServicer):
    def ValidateToken(self, request, context):
        try:
            claims = validate_access_token(request.access_token)
            return auth_pb2.TokenValidationResponse(
                active=True,
                user_id=claims["sub"],
                roles=claims["roles"],
                permissions=claims["permissions"],
            )
        except AuthenticationError:
            return auth_pb2.TokenValidationResponse(active=False)

    def GetPermissions(self, request, context):
        claims = validate_access_token(request.access_token)
        return auth_pb2.PermissionsResponse(
            user_id=claims["sub"],
            roles=claims["roles"],
            permissions=claims["permissions"],
        )


def grpc_handlers(server):
    auth_pb2_grpc.add_AuthServiceServicer_to_server(AuthServicer(), server)