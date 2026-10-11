# V37.7 통합 xingAPI schema core

목표:
RES와 JSON을 서로 다른 런타임으로 실행하지 않는다.

구조:

RES -> ResSchemaLoader --+
                         +-> TrSchema -> PacketCodec -> XingRequestPlan
JSON -> JsonSchemaLoader-+

원칙:
- 소스 어댑터만 2개
- 도메인 모델은 1개
- packet codec은 1개
- request plan은 1개
- 이후 DLL worker는 source kind를 알 필요가 없음

핵심 객체:
- FieldSchema
- BlockSchema
- TrSchema
- SchemaLoader
- ResSchemaLoader
- JsonSchemaLoader
- TrSchemaService
- PacketCodec
- XingRequestPlanner

이 구조는 OOP, 중복 제거, 테스트 용이성, 향후 TR 추가 시 코드 최소화를 우선한다.
