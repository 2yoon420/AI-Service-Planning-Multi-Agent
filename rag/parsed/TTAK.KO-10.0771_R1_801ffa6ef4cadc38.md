정 보통신단체표준(국문표준)
TTAK.KO-10.0771/R1

개정일 2015.12.16.
(2024 확인)

WoT를 위한 RESTful API 지침

RESTful API Guidelines for WoT

![image](/image/placeholder)


| T T A S t a n d a r d | 정보통신단체표준(국문표준) TTAK.KO-10.0771/R1 개정일: 2015년 12월 16일 <table><thead></thead><tbody><tr><td>WoT를 위한 RESTful API 지침</td></tr><tr><td>RESTful API Guidelines for WoT</td></tr></tbody></table> ![image](/image/placeholder)
 |
| --- | --- |


정보통신단체표준(국문표준)
TTAK.KO-10.0771/R1

개정일: 2015년 12월 16일

| WoT를 위한 RESTful API 지침 |
| --- |
| RESTful API Guidelines for WoT |


![image](/image/placeholder)


본 문서에 대한 저작권은 TTA에 있으며, TTA와 사전 협의 없이 이 문서의 전체 또는 일부를
상업적 목적으로 복제 또는 배포해서는 안 됩니다.

Copyrightⓒ Telecommunications Technology Association 2015. All Rights Reserved.

정보통신단체표준(국문표준)

서 문

# 1. 표준의 목적

REST(REpresentational State Transfer) 아키텍처는 2000년 Roy Fielding에 의해 정의
되었다. REST의 핵심 원리는 클라이언트와 서버가 URI(Uniform Resource Identifier)라
는 자원 요청 방식를 통해 요청과 응답을 구조적으로 표현하고 소통할 것인지에 있다.
REST 방식에서는 URL로 식별 및 어드레스 되는 리소스 표현을 요청하고 구조적으로 표
현된 응답 결과를 전달한다. REST는 HTTP 명령 (GET, POST, PUT 및 DELETE)을 기반
으로 클라이언트가 웹 서버에 있는 웹 자원 상태를 조회하거나 변경할 수 있도록 한다.
또한 인증(authentication), 캐싱(caching), 컨텐츠 협상(content negotiation) 등의 HTTP
원칙을 함께 활용함으로써 보다 효과적으로 웹상의 자원들을 제어하는 방법을 제공할 수
있다.

본 표준의 목적은 WoT 환경을 포함하는 다양한 웹 응용 환경에서 활용될 수 있는
RESTful API 규격 개발을 위한 지침을 제공하는 데 있다.

# 2. 주요 내용 요약

본 표준에서는 웹 기반으로 다양한 사물들을 연동하는 WoT 환경에서 활용될 수 있는
RESTful API 개발에 고려되어야 할 사항들에 대해 정의한다. 낮은 사양의 디바이스들이
주로 활용되는 사물웹 환경에서는 다양한 사물들에 대한 정보 획득과 제어 등을 위한 방
법으로 구조화된 자원 요청과 응답 방식인 REST 기반의 서비스 연결 방식이 특히 효과
적일 수 있기 때문이다.

이를 위해 본 표준에서는 웹 아키텍처의 기본 구조와 HTTP를 기반으로 하는 REST 방
식에 대한 개요를 설명하고, 효과적인 RESTful 구조를 만들 수 있도록 하기 위해 필요한
REST API 설계 원칙들을 소개한다. REST API를 설계하기 위한 일반적 설계 규칙 뿐
아니라, URI 실별자의 설계, HTTP 기반의 상호작용 방법, 메타데이타 활용 방법, 표현
방법 등에 대한 설계 원칙을 소개하고, REST API의 문서화 방법에 대해 설명함으로써
다양한 웹 응용 환경에서 적용할 수 있는 여러 고려 사항들을 함께 제공하고자 하였다.

# 3. 표준 적용 산업 분야 및 산업에 미치는 영향

본 표준은 사물인터넷 환경에서 웹 응용 서비스 환경의 활성화에 도움을 줄 수 있다.
RESTful API 가이드라인은 사물인터넷 기반 환경에서 웹 자원들을 이용하여 효과적으로
웹 응용 서비스를 개발하고 제공하는 데 도움을 줄 수 있다.

4. 참조 표준(권고)

i

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

4.1. 국외 표준(권고)

- 해당 사항 없음.

4.2. 국내 표준

- 해당 사항 없음.

5. 참조 표준(권고)과의 비교

- 5.1. 참조 표준(권고)과의 관련성


# - 해당 사항 없음.

5.2. 참조한 표준(권고)과 본 표준의 비교표

# - 해당 사항 없음.

# 6. 지식 재산권 관련 사항

본 표준의 ‘지식 재산권 확약서’ 제출 현황은 TTA 웹사이트에서 확인할 수 있다.

- ※ 본 표준을 이용하는 자는 이용함에 있어 지식 재산권이 포함되어 있을 수 있으
- 므로, 확인 후 이용한다.
- ※ 본 표준과 관련하여 접수된 확약서 이외에도 지식 재산권이 존재할 수 있다.


7. 시험 인증 관련 사항

7.1. 시험 인증 대상 여부

- 해당 사항 없음.

7.2. 시험 표준 제정 현황

- 해당 사항 없음.

- 8. 표준의 이력 정보


- 8.1. 표준의 이력


ii

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

| 판수 | 제정․개정일 | 제정․개정 내역 |
| --- | --- | --- |
| 제 1 판 | 2014.12.17. | 제정 TTAK.KO-10.0771 |
| 제 2 판 | 2015.12.16. | 개정 TTAK.KO-10.0771/R1 |


# 8.2. 주요 개정 사항

| TTAK.KO-10.0771/R1 | TTAK.KO-10.0771 | 비고 |
| --- | --- | --- |
| 3. 용어 정의 | 3. 용어 정의 | CoAP 꽌련 용어정의, 약어 추가 |
| 4. 웹 아키텍쳐와 REST | 4. 웹 아키텍쳐와 REST | CoAP과 HTTP 비교 추가 |
| 5. RESTful API 설계 규칙 | 5. RESTful API 설계 규칙 | 5.3절을 HTTP/CoAP로 제목 수정 |
| 6. RESTful API 문서화 | 6. RESTful API 문서화 | 6.4. 공통데이타 포맷을 HTTP 기반 데이터 포 맷으로 제목 수정 |


iii

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

Preface

# 1. Purpose of Standard

The standard is to define the RESTful APIs guidelines for Web of Things
Application. The REST (REpresentational State Transfer) architecture was defined in
2000 by Dr Roy Fielding. The key principles of REST are that clients and servers
(typically in an HTTP system) interact via requests and responses. These
requests/responses transfer representations of a resource; which is identified and
addressed by a Uniform Resource Locator(URL). REST promotes the use of HTTP
verbs (GET, POST, PUT, and DELETE) to allow the client to query the current state
of the resource, or to change it. By reusing these verbs, as well as HTTP
principles of authentication, caching and content negotiation; it is possible to build
relatively simple APIs based on existing Web standards.

# 2. Summary of Contents

The standard introduces the design consideration of RESTful APIs for Web of
Things Application. The REST architectural style is commonly applied to the design
of APIs for modern web application services. A REST API consists of an assembly
of interlinked resources. This set of resources is known as the REST API’s
resource model. In the context of the Web of Things, the RESTful model have
many advantages on the low-computing power devices environment such as less
overhead, less parsing complexity, statelessness, and tighter integration with HTTP.

Well-designed REST APIs can attract client developers to use the web of things
services. Some best practices for REST API design are implicit in the HTTP
standard, while other pseudo-standard approaches have emerged over the past
few years. The rules are here to help you design REST APIs with consistency that
can be leveraged by the clients that use them.

# 3. Applicable Fields of Industry and its Effect

The standard will improve to interoperability on Web of Things interfaces.

4. Reference Standards(Recommendations)

- 


4.1. International Standards(Recommendations)

- 


- None

iv

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

# 4.2. Domestic Standards

# - None

5. Relationship to Reference Standards(Recommendations)

- 


- 5.1. Relationship of Reference Standards(Recommendations)


- None

5.2. Differences between Reference Standard(Recommendation) and this Standard

- None

# 6. Statement of Intellectual Property Rights

IPRs related to the present document may have been declared to TTA. The
information pertaining to these IPRs, if any, is available on the TTA Website.

No guarantee can be given as to the existence of other IPRs not referenced on
the TTA website.

And, please make sure to check before applying the standard.

# 7. Statement of Testing and Certification

7.1. Object of Testing and Certification

- None

7.2. Standards of Testing and Certification

- None

- 8. History of Standard


- 8.1. Change History


v

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

| Edition | Issued date | Outline |
| --- | --- | --- |
| The 1st edition | 2014.12.17. | Established TTAK.KO-10.0771 |
| The 2nd edition | 2015.12.16. | Revised TTAK.KO-10.0771/R1 |


# 8.2. Revisions

| TTAK.KO-10.0771/R1 | TTAK.KO-10.0771 | Remarks |
| --- | --- | --- |
| 3. Terminology | 3. Terminology | Add CoAP description |
| 4. Web Architecture and RES | 4. Web Architecture and RES | Add CoAP and HTTP comparison |
| 5. RESTful API Design Rules | 5. RESTful API Design Rules | 5.3 title modified |
| 6. RESTful API Documentation | 6. RESTful API Documentation | 6.4. title modified |


vi

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

목 차

1. 개 요 ··········································································································································· 1
2. 표준의 구성 및 범위 ··············································································································· 1
3. 참조 표준(권고) ························································································································ 1
4. 용어 정의 및 약어 ··················································································································· 1
5. 웹 아키텍처와 REST ············································································································· 3
5.1. 웹의 구조적 특징 ············································································································ 3
5.2. REST 구조와 API ············································································································ 3
5.3. WoT와 REST ···················································································································· 4
5.4. HTTP와 CoAP ·················································································································· 4
6. RESTful API 설계 규칙 ·········································································································· 4
6.1. 일반적 설계 규칙 ············································································································ 4
6.2. URI 식별자 설계 ·············································································································· 8
6.3. HTTP/CoAp를 이용한 상호작용 설계 ········································································ 9
6.4. 메타데이타 설계 ············································································································ 10
6.5. 표현 설계 ························································································································ 11
6.6. 기타 ·································································································································· 12
7. RESTful API 문서화 ·············································································································· 12
7.1. API 문서화 ······················································································································ 12
7.2. 오류 처리 ························································································································ 13
7.3. 예시 ·································································································································· 14
7.4. HTTP 기반 데이터 포맷 ······························································································ 15
7.5. 국제화 ······························································································································ 16
7.6. 하위 호환성 ···················································································································· 17
7.7. 상위 호환성, 확장성 ····································································································· 19
부록 Ⅰ. CoAP 동작 방식 사례 ······························································································· 20
부록 Ⅱ. 참조 문헌 ····················································································································· 21

TTAK.KO-10.0771/R1

vii

정보통신단체표준(국문표준)

Content

1. Introduction ······························································································································· 1
2. Structure and Scope ············································································································· 1
3. Reference Standards(Recommendations) ······································································· 1
4. Terms Definition and Abbreviations ·················································································· 1
5. Web Architecture and REST ······························································································ 3
5.1. Web Architecture ············································································································ 3
5.2. REST Architecture and API ························································································· 3
5.3. WoT and REST ··············································································································· 4
5.4. HTTP and CoAp ············································································································· 4
6. RESTful API Design Rules ··································································································· 4
6.1. General Design Rules ··································································································· 4
6.2. URI Identifier Design ····································································································· 8
6.3. HTTP/CoAP Interaction Design ················································································· 9
6.4. Metadata Design ·········································································································· 10
6.5. Representation Design ······························································································· 11
6.6. Misc ·································································································································· 12
7. RESTful API Documentation ······························································································ 12
7.1. API Documentation ······································································································ 12
7.2. Failure Processing ······································································································· 13
7.3. Examples ························································································································ 14
7.4. Data Format on HTTP ································································································ 15
7.5. I18N(Internationalization) ··························································································· 16
7.6. Backward Compatability ···························································································· 17
7.7. Forward Compatability, Extensibility ······································································ 19
Appendix Ⅰ. Case of CoAP Operation ············································································ 20
Appendix Ⅱ. Reference ··········································································································· 21

TTAK.KO-10.0771/R1

viii

정보통신단체표준(국문표준)

# WoT를 위한 RESTful API 지침
(RESTful API Guidelines for WoT)

1. 개요

본 표준은 WoT 환경에서 효과적으로 다양한 웹 자원들을 공유하고 접근 제어하기 위
해 사용되는 RESTful API에 대한 가이드라인을 정의한다. REST는 웹을 보다 확장성 있
게 활용할 수 있도록 웹의 제약성을 인식하고 이를 기반으로 보다 효과적인 웹 서비스를
제공하기 위한 구조적 설계 원칙이다. REST 기반 인터페이스 방식은 HTTP과 URI를 기
반으로 하는 인터페이스 방식으로 소형의 단말이나 저사양 단말 환경에서 효과적으로 시
스템 인터페이스를 제공할 수 있는 방법이다.

# 2. 표준의 구성 및 범위

본 표준은 총 6개의 장으로 구성되어 있고, 웹의 기본적인 구조와 REST 방식에 대한
개요를 소개하고, REST 기반의 API 설계 원칙들을 정의하며, RESTful API 문서화 및 고
려 사항들에 대해 정의하고 있다.

3 . 참조 표준(권고)

3.1. 국외 표준(권고)

- 해당 사항 없음.

3.2. 국내 표준

- 해당 사항 없음.

- 4. 용어 정의 및 약어


4.1. 기술 용어

4.1.1. HATEOAS

REST의 “애플리케이션 상태의 엔진으로서의 하이퍼미디어Hypermedia as the
Engine of Application State” 단일 인터페이스 제약을 나타내는 두문자어로, 리
소스의 가능한 액션을 지정할 수 있는 연결에 대한 상태-인지state-aware 목록
을 제공하는 관습을 지칭하는 말이다.

1

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

# 4.1.2. 자바스크립트 객체 표현(JSON, JavaScript Object Notation)

자바스크립트를 기반으로 name/value 형태의 쌍으로 표현되는 구조적 데이터 교환
을 위해 사용되는 표준화된 텍스트 형식이다. 이 형식은 사람이 읽고 쓰기에 용이
하며, 기계가 분석하고 생성함에도 용이하다.

# 4.1.3. 웹 클라이언트

자원 상태 표현을 받거나 서버로 전송하기 위해 REST 단일 인터페이스에 따르는
클라이언트 프로그램

# 4.1.4. CRUD(Create, Retrieve, Update, Delete)

네 가지 전형적인 제어 명령인 생성Create, 검색Retrieve, 갱신Update, 삭제Delete
를 의미

# 4.1.4. HTTP (HyperText Transfer Protocol)

웹 서버와 웹 클라이언트간의 웹 자원 정보 송수신하는 데 사용되는 클라이언트/서
버 프로토콜

# 4.1.5. WoT (Web of Things)

웹 기반으로 사물(Thing)들을 연결하고 제어/관리하며 다양한 응용들을 제공할 수
있도록 하기 위한 기술들을 통칭

# 4.1.6. CoAP (Constrained Application Protocl)

저전력 환경에 저성능 CPU와 저용량 메모리 등의 제약을 갖는 저사양 디바이스에
서 동작될 수 있도록 HTTP 프로토코를 변형한 새로운 프로토콜

4.2. 약어

API Application Programming Interface
ASCII American Standard Code for Information Interchange
CLRF Carriage Return Line Feed
CoAP Constrained Application Protocol
CRUD Create, Read, Update, Delete
HTML HyperText Markup Language
HTTP HyperText Transfer Protocol
IRI Internationalized Resource Identifier

2

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

| JSON | Java Script Object Notation |
| --- | --- |
| MIME | Multipurpose Internet Mail Extensions |
| MMS | Multimedia Message Service |
| REST | REpresentational State Transfer |
| URI | Uniform Resource Identifier |
| URL | Uniform Resource Locator |
| URN | Uniform Resource Name |
| UTF | Universal Transformation Format |
| W3C | World Wide Web Consortium |
| XML | Extensible Markup Language |


# 5. 웹 아키텍처와 REST

# 5.1. 웹의 구조적 특징

1989년에 최초로 그 아이디어가 세상에 공개된 웹 기술은 HTML(HyperText Markup
Language), URL(Unified Resource Locator, HTTP(HyperText Transfer Protocol)이라는
세 가지 기술을 기초로 간단한 문서와 자원들을 공유하기 위한 목적으로 출발하였다. 이
후 1994년 기술 표준화를 위한 W3C(World Wide Web Consortium)가 창립되면서 웹 기
술은 눈부신 진보와 함께 인류 생활에 있어 없어서는 안 될 중요한 기반 기술로 발전해
왔다.

1993년 HTTP 규약을 설계한 로이 필딩(Roy Fielding)은 웹의 제약점들을 해소하고 확
장하기 위해 다음과 같이 웹의 제약점들을 여섯 가지 범주로 묶어 웹의 구조적 스타일
(Web’s architectural style)이라고 정의하였다.

- 1. 클라이언트/서버(Client/Server) : 제공자와 이용자로 나누어 각각의 기술 사용 가능
- 2. 일관된 인터페이스(Uniform Interface) : 모든 인터페이스는 표준에 기반 일관성 유지
- 3. 계층 시스템(Layered System) : 시스템을 더 계층화시키고 나눌 수 있다.
- 4. 캐시(Cache) : 클라이언트와 서버의 통신횟수와 양을 감소시킨다.
- 5. 상태 없음(stateless) : 서버 측에서의 애플리케이션의 상태를 가지지 않는다.
- 6. 주문형 코드(Code on demand) : 클라이언트에 다운로드하여 해석하고 실행한다.


이러한 제약점과 특징들은 웹의 기본적인 구조로서, 이러한 구조적 특징들을 이해하고
효과적으로 제약점을 활용할 때에만 효과적인 웹 응용과 서비스를 개발할 수 있다.

# 5.2. REST 구조와 API

2000년 로이 필딩은 웹의 구조적 특징에 기반한 설계 방식을 제안하였는데, 이것이
REST(REpresentational State Transfer)라는 구조 설계 방식의 시작이다.

3

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

REST 구조 스타일은 웹 서비스를 위한 API 설계에 많이 적용되고 있으며, REST 구조
스타일에 적합한 웹 API를 RESTful API(또는 REST API)라고 한다. 이러한 RESTful API
는 상호 연결된 리소스의 결합체이며, 이 리소스 집합을 통칭하여 RESTful API의 리소스
모델이라고 한다.

# 5.3. WoT와 REST

웹 기반으로 사물들을 연결하고 제어/관리하며 다양한 응용들을 제공할 수 있도록 하
기 위한 기술들을 통칭하여 “사물 웹(Web of Things)” 기술로 부르고 있으며, 이중에서
도 HTTP 프로토콜을 기반으로 연결을 단순화하고 제어 방식을 통일시키기 위해 REST
구조와 설계 방식을 많이 활용하고 있다.

# 5.4. HTTP와 CoAP

RESTful 구조 설계를 위해 사용되는 핵심 프로토콜은 HTTP였으나, 저사양의 제약 단
말환경에서도 REStful 구조를 사용할 수 있도록 하기 위해 IETF에 CoRE(Constrained
RESTful environments) WG이 구성되고 CoAP을 개발하면서 HTTP와 CoAP 모두가
RESTful용 프로토콜로 활용되고 있다.

HTTP와 CoAP 프로토콜 스택의 기본적인 차이는 <그림 5-1>과 같다. HTTP는 다양한
단말 환경에서 사용될 수 있는 TCP 기반의 범용 프로토콜이며, CoAP은 저전력
6LoWPAN 환경에서 UDP 기반의 통신을 하는 저사양 단말에 특화된 프로토콜이라 할 수
있다.

![image](/image/placeholder)


(그림 5-1) HTTP와 CoAP 프로토콜 비교

6. RESTful API 설계 규칙

6.1. 일반적 설계 규칙

4

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

1. 우선적으로 가장 중요하고 고려할 점은 RESTful API의 사용 대상이 전형적인 웹 개발
자들이라는 것이다. 이들 개발자는 개별 서비스에 대한 세부적인 이해가 없고 주요 인
터넷 업체, 서비스 공급자 또는 플랫폼 서비스를 사용하는 것처럼 간단하게 RESTful
서비스를 이용할 수 있어야 한다고 가정해야 한다.

따라서 RESTful API는 웹 상에서 제공되는 다른 인기 RESTful 서비스와 동일한 수
준의 사용 용이성을 제공해야 한다. 더불어 언제나 RESTful API는 최종 사용자(예:
웹사이트, 포털)를 대신해 동작하는 애플리케이션, 즉 다른 자동화된 웹 서비스들을
통해서도 사용될 수 있다고 가정해야 한다.

만약 RESTful API가 특정 클라이언트 환경에 제대로 서비스를 제공하지 못하는 경
우가 있다면 이를 파악하여 분석하고 문서화하며 해결해야 한다.

# 2. RESTful API 규격은 다음과 같은 REST & HTTP 관행을 따라야 한다.

가. URL로서 주소 지정이 가능한 리소스의 관점에서 서비스가 정의되어야 한다.
나. URL에서는 동사보다 명사의 사용을 권장한다.

- Ÿ URL은 리소스 식별
- Ÿ HTTP 메서드는 작업 식별


다. CRUD가 적합한 모든 인터페이스에 대하여 다음과 같은 매핑을 활용하여
CRUD(Create, Read, Update, Delete) 작업을 위한 HTTP 동사, 즉, POST, GET,
PUT, DELETE를 사용한다.

Ÿ POST

- (1) HTTP 클라이언트가 HTTP 서버에 동일한 지정된 리소스의 하위 리소스를 생성
- (즉, 새로운 수의 리소스 컬렉션(resource collection)을 생성)하라는 요청을 보
- 낼 경우, POST는 서버 측 알고리즘을 사용하여 Create로 매핑된다.
- (2) HTTP 클라이언트가 HTTP 서버에 지정된 리소스를 부분적으로 업데이트하거
- 나, 지정된 리소스의 하위 리소스를 하나 이상 업데이트하라는 요청을 보낼 경
- 우, POST는 서버 측 알고리즘을 사용하여 Update로 매핑된다. (주: 일부의 경
- 우에는 작업이 CRUD 작업에 매핑될 수 없을 때 POST가 사용되기도 한다. 예
- 를 들어 리소스 공간의 변형 업데이트는 일반적으로 CRUD 작업으로 매핑하기
- 가 어렵다(예: 배치(batch) 업데이트 등)


- Ÿ GET은 Read로 매핑된다. GET은 안전해야 하고 (즉 리소스를 변경할 수 없고),
- 반드시 멱등이어야 한다(즉, 다른 누군가가 호출 간에 리소스를 변경하지 않은 이
- 상, 여러 차례 호출한 결과가 한 번 호출한 결과와 같다).
- Ÿ PUT


- (1) PUT 작업에 의해 어드레싱되는 URL이 기존의 리소스를 가리킬 경우, PUT은
- 리소스의 Update 전체에 매핑되며, 반드시 멱등이 되어야 한다.
- (2) PUT 작업에 의해 어드레싱되는 URL이 기존의 리소스를 가리키지 않을 경우,
- 해당 작업이 허용되지 않는다면 PUT이 해당 리소스의 Create에 매핑된다.


5

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

# Ÿ DELETE는 Delete로 매핑되며, 반드시 멱등(@@)이 되어야 한다.

라. 성공적인 작업과 실패한 작업 모두에 대한 응답으로 표준 HTTP 상태 코드를 사용
한다. 실패한 작업의 경우, 응답의 본문에 실패한 연산의 추가 상태 정보(존재하는
경우)가 반환된다.

응답 시 HTTP 상태 코드 사용은 [RFC2616] 표준에 부합해야 하고, 성공적 작업의 경
우 다음과 같은 상태 코드를 사용할 것을 권장한다.

# POST: 성공적 응답의 경우, 허용되는 값은 아래와 같다.

- l 200 (OK): 응답에 리소스 URL이 제공되지 않지만 응답 본문에 결과를 설명해주는
- 개체가 포함될 경우
- l 201 (Created): 원본 서버에서 리소스가 생성된 경우, 메시지 본문에는 요청 상태를
- 설명하고 새로운 리소스 및 위치 헤더를 명시하는 개체가 포함되어 있어야 한
- 다.
- l 204 (No content): 응답에 URL이 제공되지 않고 본문도 제공하지 않을 경우


# PUT:

- l 200 (OK) 또는 204(No Content): 기존의 리소스가 수정된 경우 사용된다(멱등).
- l 201 (Created): 새로운 리소스가 생성될 경우 반드시 사용되어야 한다.


# GET: (idempotent)

l 200 (OK): 요청된 개체를 포함하고 있는 성공적 응답

# DELETE: (idempotent)

- l 200 (OK): 성공적 응답의 경우, 응답에 상태를 설명하는 개체가 포함된 경우
- l 202 (Accepted): 동작이 아직 이루어지지 않은 경우
- l 204 (No Content): 동작이 이루어졌지만 응답이 개체를 포함하지 않은 경우


3. 응답에 사용된 컨텐츠 타입은 다음과 같은 메서드를 사용하여 설정된다.

일반적으로, 응답 메시지 본문에 사용되는 컨텐츠는 반드시 요청 본문에 사용된 컨
텐츠 타입과 반드시 일치해야 한다. 이것이 불가능할 경우, 컨텐츠 타입 협상이 사용
될 수 있다. 컨텐츠 타입 협상 메서드는 요청의 “Accept” HTTP 헤더를 기반으로 지
원되는 컨텐츠 타입을 나타낸다. “resFormat”이라는 이름의 매개변수를 부여하여 이
헤더의 정보를 오버라이드 할 수 있다.

최소한 XML과 JSON 컨텐츠 타입이 지원되고, 다른 컨텐츠 타입은 사례별로 선택적
으로 지원되어 구체적으로 문서화된다(예를 들어, GET을 사용할 때에는 URL에 단순

6

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

한 이름-값 쌍(name-value pair) 매개변수가 허용되고, POST를 사용할 때에는 요청
메시지 본문에 application/x-www-form-urlencoded가 지원될 수 있다).

4. 리소스 URL 경로에 API 버전을 삽입하여(예: “v1”) API 버전을 지정할 것을 권고한다.
버전은 이전의 1.0 버전과는 완전 별개의 리소스/엔드포인트(endpoint) 집합이다.

- 가. 사소한 API 개정은 하위 호환되며(일반적으로, 상위 호환성을 위해서는 알려지지
- 않은 매개변수가 무시되어야 한다), 주요 개정은 고유의 경로 집합이다.
- 나. 하위 호환되지 않는 XML 요청/응답 포맷이 변경될 경우 반드시 주 버전 번호가 증
- 가되어야 하며, 그렇지 않을 경우 부 버전 번호가 증가되어야 한다.
- 다. XML 스키마의 네임스페이스 URN에는 주 버전 번호만이 포함된다(예:
- urn:oma:xml:rest:netapi:common:1).
- 라. 전체 버전 번호는 XML 스키마의 <schema> 요소에 “version” 특성에서 부여된다
- (주 버전 번호와 부 버전 번호는 “.” 문자로 구분).
- 마. 리소스 URL은 문자 “v” 다음에 경로의 주 버전 번호만을 포함한다(예: “v1”).


예: 예를 들어 “메시징 서비스”가 버전 1.0, 1.1... 2.0, 2.1 등을 지원할 경우, 리소스
URL의 API 버전은 다음과 같이 표현된다.

- l 1.0, 1.1, 1.x 버전의 경우, http://example.com/exampleAPI/messaging/v1/
- l “메시징” 서비스의 2.0, 2.1, 2.x 버전의 경우
- http://example.com/exampleAPI/messaging/v2/


5. 콜백(callback) API 규격 및 콜백 API의 클라이언트의 구현 등에서는 본 문서의 나머
지 지침을 준수해야 한다.

- 가. 예를 들어 클라이언트가 서버와 유사한 환경에 존재할 경우, 요청 URL은 클라이언
- 트가 가입되어 있는 특정 이벤트를 통지 받을 수 있는 클라이언트에 의해 전달될
- 수 있다.
- 나. 모든 경우에 있어서, 특정 클라이언트 액세스의 특이성을 분석하여 사례별로 다른
- 접근법을 따를 수도 있다.


- 6. API 규격은 예시를 포함해야 한다. RESTful API 설명의 예시에서는 실제 호스트나 업
- 체 실명을 가급적 사용하지 말아야 한다(www.carrier.com대신 www.example.com ,
- “myapp.developer.com” 등을 사용).


- 7. 클라이언트 요청이나 서버 콜백 요청의 일부로 여러 첨부 자료를 전송해야 할 경우,
- MIME 컨텐츠 타입 multipart/related를 사용해야 한다.


- 8. API는 유용성을 증진시키기 위해 요청/응답 본문에 추가 데이터 요소를 추가하고 URL
- 에 추가 쿼리 매개변수를 추가하는 능력을 지원해야 한다.
- (주: 클라이언트와 서버는 상위 호환성을 이유로 인식되지 않는 매개변수와 데이터


7

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

# 요소를 무시해야 한다).

9. (계정 관리 및 지불 API에서와 같이) 메시지에 비밀번호, 계좌 번호 및 카드 번호와 같
이 민감한 데이터가 들어있을 경우, 이들 정보를 보호하기 위한 보안이 고려되어야 한
다.

- 


10. HTTP 프로토콜은 RFC2616에 따라 URL 길이에 사전적 제한을 두지 않는다. 하지만
일부 오래된 구현은 256 바이트의 일정한 제한을 두거나 최소 4000자 이상으로 제한
을 두기도 한다. 255바이트 이상 URL의 GET 기반 양식은 414 (Request-URI Too
Long) 상태 코드를 포함한 응답을 받을 수 있다. URL이 4000자를 넘을 경우, API 설
계는 사례별로 GET 대신 POST 메서드를 활용하는 방안을 고려할 것이다.

# 6.2. URI 식별자 설계

RESTful API는 리소스를 나타낼 때 URI를 사용한다. 그러므로 효과적인 URI 사용 설계
가 효과적인 RESTful API 설계의 기본 요소가 된다.

# 6.2.1. URI 형태

- l 규칙1-1: 슬래시 구분자(/)는 계층 관계를 나타내는 데 사용한다.
- l 규칙1-2: URI 마지막 문자로 슬래시(/)를 포함하지 않는다.
- l 규칙1-3: 하이픈(-)은 URI 가독성을 높이는 데 사용한다.
- l 규칙1-4: 밑줄(_)은 URI에 사용하지 않는다.
- l 규칙1-5: URI 경로에는 소문자가 적합하다.
- l 규칙1-6: 파일 확장자는 URI에 포함시키지 않는다.


# 6.2.2. URI 권한 설계

- l 규칙1-7: API에 있어서 서브 도메인은 일관성 있게 사용해야 한다.
- l 규칙1-8: 클라이언트 개발자 포탈 서브 도메인 이름은 일관성 있게 만들어야 한다.


# 6.2.3. URI 경로 디자인

- l 규칙1-9: 도큐먼트 이름으로는 단수 명사를 사용해야 한다.
- l 규칙1-10: 컬렉션 이름으로는 복수 명사를 사용해야 한다.
- l 규칙1-11: 스토어 이름으로는 복수 명사를 사용해야 한다.
- l 규칙1-12: 컨트롤러 이름으로는 동사나 동사구를 사용해야 한다.
- l 규칙1-13: 경로 부분 중 변하는 부분은 유일한 값으로 대체한다.
- l 규칙1-14: CRUD 기능을 나타내는 것은 URI에 사용하지 않는다.


8

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

# 6.2.4. URI Query 디자인

- l 규칙1-15: URI 쿼리 부분으로 컬렉션이나 스토어를 필터링할 수 있다.
- l 규칙1-16: URI 쿼리는 컬렉션이나 스토어의 결과를 페이지로 구분하여 나타내는 데
- 사용해야 한다.
- l 규칙1-17: 저사양 단말 환경까지 지원해야 할 경우, CoAP과 HTTP 호환성을 고려한
- URI 설계를 해야 한다.


# 6.3. HTTP/CoAP을 이용한 상호작용 설계

RESTful API는 HTTP/CoAP 규약을 기반으로 리소스를 요청하고 제공 받는 구조로 설
계된다. 그러므로 응답 요청과 응답 상태 코드를 효과적으로 활용해야 한다.

# 6.3.1. 요청 메서드

- l 규칙2-1: GET 메서드나 POST 메서드를 사용하여 다른 요청 메서드를 처리해서는 안
- 된다.
- l 규칙2-2: GET 메서드는 리소스의 상태 표현을 얻는 데 사용해야 한다.
- l 규칙2-3: 응답 헤더를 가져올 때는 반드시 HEAD 메서드를 사용해야 한다.
- l 규칙2-4: PUT 메서드는 리소스를 삽입하거나 저장된 리소스를 갱신하는 데 사용해야
- 한다.
- l 규칙2-5: PUT 메서드는 변경 가능한 리소스를 갱신하는 데 사용해야 한다.
- l 규칙2-6: POST 메서드는 컬렉션에 새로운 리소스를 만드는 데 사용해야 한다.
- l 규칙2-7: POST 메서드는 컨트롤러를 실행하는 데 사용해야 한다.
- l 규칙2-8: DELETE 메서드는 그 부모에서 리소스를 삭제하는 데 사용해야 한다.
- l 규칙2-9: OPTIONS 메서드는 리소스의 사용 가능한 인터랙션을 기술한 메타데이터를
- 가져오는 데 사용해야 한다.


# 6.3.2. 응답 상태 코드

- l 규칙2-10: 200(“OK”)는 일반적인 요청 성공을 나타내는 데 사용해야 한다.
- l 규칙2-11: 200(“OK”)는 응답 바디에 에러를 전송하는 데 사용해서는 안 된다.
- l 규칙2-12: 201(“Created”)는 성공적으로 리소스를 생성했을 때 사용해야 한다.
- l 규칙2-13: 202(“Accepted”)는 비동기 처리가 성공적으로 시작되었음을 알릴 때 사용
- 해야 한다.
- l 규칙2-14: 204(“No Content”)는 응답 바디에 의도적으로 아무것도 포함하지 않을 때
- 사용한다.
- l 규칙2-15: 301(“Moved Permanently”)는 리소스를 이동시켰을 때 사용한다.
- l 규칙2-16: 302(“Found”)는 사용하지 않는다.


9

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

- l 규칙2-17: 303(“See Other”)은 다른 URI를 참조하라고 알려줄 때 사용한다.
- l 규칙2-18: 304(“Not Modified”)는 대역폭을 절약할 때 사용한다.
- l 규칙2-19: 307(“Temporary Redirect”)은 클라이언트가 다른 URI로 요청을 다시 보내
- 게 할 때 사용해야 한다.
- l 규칙2-20: 400(“Bad Request”)은 일반적인 요청 실패에 사용해야 한다.
- l 규칙2-21: 401(“Unauthorized”)은 클라이언트 인증에 문제가 있을 때 사용해야 한다.
- l 규칙2-22: 403(“Forbidden”)은 인증 상태에 상관없이 액세스를 금지할 때 사용해야
- 한다.
- l 규칙2-23: 404(“Not Found”)는 요청 URI에 해당하는 리소스가 없을 때 사용해야 한
- 다.
- l 규칙2-24: 405(“Method Not Allowed”)는 HTTP 메서드가 지원되지 않을 때 사용해
- 야 한다.
- l 규칙2-25: 406(”Not Acceptable”)은 요청된 리소스 미디어 타입을 제공하지 못할 때
- 사용해야 한다.
- l 규칙2-26: 409(“Conflict”)는 리소스 상태에 위반되는 행위를 했을 때 사용해야 한다.
- l 규칙2-27: 412(“Precondition Failed”)는 조건부 연산을 지원할 때 사용한다.
- l 규칙2-28: 415(“Unsupported Media Type”)은 요청의 페이로드에 있는 미디어 타입
- 이 처리되지 못했을 때 사용해야 한다.
- l 규칙2-29: 500(“Internal Server Error”)는 API가 잘못 작동할 때 사용해야 한다.


# 6 .4. 메타데이타 설계

RESTful API에서는 HTTP 요청 메시지와 응답 메시지에 포함된 헤더를 통해 여러 형태
의 메타데이터가 함께 전달된다. 그러므로 HTTP 헤더와 미디어 타입을 효과적으로 활용
해야 한다.

# 6.4.1. HTTP 헤더

- l 규칙3-1: Content-Type을 사용해야 한다.
- l 규칙3-2: Content-Length를 사용해야 한다.
- l 규칙3-3: Last-Modified는 응답에 사용해야 한다.
- l 규칙3-4: ETag는 응답에 사용해야 한다.
- l 규칙3-5: 스토어는 조건부 PUT 요청을 지원해야 한다.
- l 규칙3-6: Location은 새로 생성된 리소스의 URI를 나타내는 데 사용해야 한다.
- l 규칙3-7: Cache-Control, Expires, Date 응답 헤더는 캐시 사용을 권장하는 데 사용
- 해야 한다.
- l 규칙3-8: Cache-Control, Expires, Pragma 응답 헤더는 캐시 사용을 중지하는 데
- 사용해야 한다.
- l 규칙3-9: 캐시 기능은 사용해야 한다.


10

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

- l 규칙3-10: 만기 캐싱 헤더는 200(“OK”) 응답에 사용해야 한다.
- l 규칙3-11: 만기 캐싱 헤더는 ‘3xx’ 와 ‘4xx’ 응답에 선택적으로 사용될 수 있다.
- l 규칙3-12: 커스텀 HTTP 헤더는 HTTP 메서드의 행동을 바꾸는 데 사용해서는 안 된
- 다.


# 6.4.2. 미디어 타입

- l 규칙3-13: 애플리케이션 고유 미디어 타입을 사용해야 한다.
- l 규칙3-14: 리소스의 표현이 여러 가지 가능할 경우 미디어 타입 협상을 지원해야 한
- 다.
- l 규칙3-15: query 변수를 사용한 미디어 타입 선택을 지원할 수 있다.


# 6.5. 표현 설계

RESTful API에서는 요청 받은 내용에 대한 응답 메시지를 정해진 표현 방법에 따라 전
송을 하게 된다. 그러므로 일관성 있는 메시지 표현과 오류 표현 방법을 사용하여야 한
다.

# 6.5.1. 메시지 바디 포맷

- l 규칙4-1: JSON 리소스 표현을 지원해야 한다.
- l 규칙4-2: JSON은 문법에 잘 맞아야 한다.
- l 규칙4-3: XML과 다른 표현 형식은 선택적으로 지원할 수 있다.
- l 규칙4-4: 중첩된 메시지 포맷으로 표현하지 않는다.


# 6.5.2. 하이퍼미디어 표현

- l 규칙4-5: 링크는 일관된 형태로 나타내야 한다.
- l 규칙4-6: “rel” 속성으로 링크 관계를 표현할 때에는 일관된 형태를 사용해야 한다.


# 6.5.3. 미디어 타입 표현

l 규칙4-7: 미디어 타입을 표현할 때는 일관성 있는 형식을 사용해야 한다.

# 6.5.4. 오류 표현

- l 규칙4-8: 오류는 일관성 있게 표현한다.
- l 규칙4-9: 오류 응답은 일관성 있게 표현한다.
- l 규칙4-10: 일반적인 오류 상황에서는 일관성 있는 오류 타입을 사용해야 한다.


11

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

# 6.6. 기타

# 6.6.1. 버전

l 규칙: 새로운 개념을 도입하려면 새로운 URI를 사용해야 한다.

# 6.6.2. 보안

l 규칙: 리소스 보호를 위해 OAuth를 사용할 수 있다.

# 7. RESTful API 문서화

# 7.1. API 문서화

각 RESTful API는 리소스 지향적으로 지정되어야 하고, API에 의해 사용되는 리소스가
정의 및 설명되어야 한다. 또한 사용 사례(use case) 및 시퀀스 다이어그램이 제공되어
야 한다. 각 RESTful API 규격은 반드시 다음 정의를 포함해야 한다.

- l 복수의 리소스가 API에서 정의될 경우, 전반적인 구조와 더불어 API 리소스 정의
- l 각 리소스의 HTTP/CoAP 작업 정의 (동사: GET, POST, PUT, DELETE)
- l 복합 데이터 타입 및 열거형 타입 등의 데이터 타입 정의


- l 작업 설명
- l 요청
- l 응답
- l 참조 오류


URL의 모든 매개변수는 반드시 URL 인코딩을 거쳐야 하고(예: ‘endUserId’), 설명 매
개변수는 endUserId=tel%3A%2B19585550100 및
description=Some%20billing%20information처럼 인코딩되어야 한다.

# 7.1.1. API 데이터 타입

RESTful API 데이터 타입 및 열거형 타입은 반드시 옵션 여부를 포함한 세부적인 관련
설명과 함께 지정되어야 한다. 이를 통해 개발자는 매개변수를 어떻게 사용하는지를 이
해할 수 있다. API 데이터 타입 정의는 반드시 일관적이고 공인된 표준 정의를 따라야
한다: 다음의 표는 예이다.

<표 7-1> API 데이터 타입 예시

| 요소 | 타입 | 옵션 | 설명 |
| --- | --- | --- | --- |


12

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

| 요소 | 타입 | 옵션 | 설명 |
| --- | --- | --- | --- |
| destinationAddress | xsd:anyURI | No | 호출된 메시징 서비스와 관련 된 숫자. 즉, 터미널이 메시지 전송에 사용하는 목적지 주소 (예: 'sip' URI, 'tel' URI, 'acr' URI) |
| senderAddress | xsd:anyURI | No | 응답 메시지가 전송될 수 있 는 발신자 주소(예: 'sip' URI, 'tel' URI, 'acr' URI). senderAddress 또한 요청 URL의 일부일 경우, 두 MUST의 값이 같아야 한다. |
| dateTime | xsd:dateTime | Yes | 운영자에 의해 메시지가 수신 된 시간 |
| resourceURL | xsd:anyURI | Yes | 자기 참조 URL. resourceURL 은 클라이언트에 의한 POST 요청에는 포함되지 않지만, 완전한 리소스 표현이 통지에 내장되어 있을 경우에는 서버 에 의한 클라이언트 통지를 나타내는 POST 요청에는 반 드시 포함되어야 한다. 또한 resourceURL은 특정 개체 본 문을 반환하는 모든 HTTP/CoAP 메서드에 대한 응답과 PUT 요청에도 포함되 어야 한다. |
| link | common:Link[0..unbound ed] | Yes | 리소스와 관련이 있는 다른 리소스에 대한 링크 |
| messageId | xsd:string | Yes | 서버가 생성한 메시지 식별자. 메시지 타입이 단순 텍스트 SMS와 다를 경우 반드시 이 필드가 있어야 한다. 즉, 아래 선택 요소에 InboundSMSTextMessage 이 외의 타입이 있어야 한다. |
| inboundSMSTextMessag e | InboundSMSTextMessage | Choic e | 인바운드 SMS 텍스트 메시지 |
| inboundMMSMessage | InboundMMSMessage | Choic e | 인바운드 MMS 메시지 |
| inboundIMMessage | InboundIMMessage | Choic e | 인바운드 IM 메시지 |
| destinationAddress | xsd:anyURI | No | 메시징 서비스에 연계된 번호, 즉 터미널에 의해 메시지 전송에 사용되는 목적지 주소 (예: 'sip' URI, 'tel' URI, 'acr' URI) |


또한 복수의 API에 걸쳐 공통적인 데이터 타입이 일관되게 재사용되어야 한다.

# 7.2. 오류 처리

서버는 REST 요청 메시지를 수신하고 해석한 후, RFC2616에 정의된 바와 같이
HTTP/CoAP 응답 메시지로 응답한다.

Response = Status-Line

*(( general-header

13

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

| response-header
| entity-header ) CRLF)
CRLF
[ message-body ]

# Status-Line = HTTP-Version SP Status-Code SP Reason-Phrase CRLF

위의 “Status-Code” 및 “Reason-Phrase”에는 표준 상태 코드 값과 사유 어구가 사
용된다. 해당되는 경우 모든 오류에 대하여 메시지 본문을 통해 추가 정보가 요청자에게
반환되어야 한다. 메시지 본문에는 오류 코드와 오류 설명 등의 자세한 오류 내역이 수
록되어야 한다. 반환되는 정보는 클라이언트가 상태 정보를 저장할 필요가 없도록 자족
적이어야 한다. 표는 지원되는 리소스 포맷을 제시한다.

# 7.3. 예시

API 규격에는 예시가 포함되어야 한다. RESTful API 설명의 예시에서는 실제 호스트나
업체 실명을 사용하지 말아야 한다(“myapp.developer.com” 대신 www.carrier.com,
www.example.com 등을 사용).

또한 RESTful API의 설명은 독자의 편의를 위해 HTTP-XML 포맷으로 세부적인 샘플
요청 및 응답 메시지를 포함해야 한다. 예를 들어, REST
<GetMessageDeliveryStatusRequest> Request 샘플은 다음을 포함해야 한다:

GET /exampleAPI/messaging/v1/outbound/tel%3A%2B19585550151/requests/req123/deliveryInfos HTTP/1.1
Accept: application/xml
Host: example.com

또한 최종 샘플 REST 응답은 다음과 같은 형식으로 표현된다.

14

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

HTTP/1.1 200 OK
Content-Type: application/xml
Content-Length: nnnn
Date: Thu, 04 Jun 2009 02:51:59 GMT

# <?xml version="1.0" encoding="UTF-8"?>
<msg:deliveryInfoList xmlns:msg="urn:oma:xml:rest:netapi:messaging:1">

<resourceURL>http://example.com/exampleAPI/messaging/v1/outbound/tel%3A%2B19585550100/requests/r
eq123/deliveryInfos

</resourceURL>
<deliveryInfo>
<address>tel:+19585550103</address>
<deliveryStatus>MessageWaiting</deliveryStatus>
</deliveryInfo>
<deliveryInfo>
<address>tel:+19585550104</address>
<deliveryStatus>MessageWaiting</deliveryStatus>
</deliveryInfo>
</msg:deliveryInfoList>

7.4. hTTP 기반 데이터 포맷

# 7.4.1. XML

POST 및 PUT 요청은 XML 포맷의 데이터를 포함할 수 있다. 이러한 경우
“application/xml” 본문이 사용되어야 한다. 이 XML 포맷은 해당 데이터 타입의 XML 스
키마와 부합해야 한다. XML에 OMA SUP 스키마 파일 포인터가 포함되어 있을 경우, 온
라인으로 유효성이 검사될 수 있다.

응답은 XML 본문을 포함할 수 있다.

# 7.4.2. JSON

POST 및 PUT 요청은 JSON 포맷의 데이터를 포함할 수 있다 [JSON]. 이 포맷에 대
한 자세한 사항은 JSON [RFC4627]에서 찾을 수 있다. 응답에는 또한 JSON 포맷의 본
문이 포함될 수 있다. [REST_NetAPI_Common]에는 HTTP 요청/응답의 JSON 인코딩을
위한 직렬화(serialization) 규칙이 명시된다.

7.4.3. Application/x-www-form-urlencoded

XML 또는 JSON의 대안으로, (응답이 아닌) 요청의 입력 데이터는 [HTML_FORMS]에
명시된 바와 같이 application/x-www-form-urlencoded 포맷으로 제출될 수 있다. 일반
적으로 이 포맷은 [RFC2616]에 의해 정의된 URL의 마지막 부분으로 활용된다. RESTful

15

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

API에서는 이 포맷이 쿼리 매개변수로 사용될 수 있는 GET/DELETE 요청에 이러한 사항
이 적용된다.

POST 요청에서 이 포맷은 또한 웹 브라우저에 의해 데이터 구조 표현을 HTML 폼으로
부터 직접 제출하는 사용 사례를 지원하도록 사용될 수 있다. 이는
application/x-www-form-urlencoded 본문이 포함됨을 의미한다. 웹 브라우저는 POST
를 활용하여 이러한 폼을 제출하므로, 일반적으로 PUT 요청 본문에 이 형식을 사용하는
것은 의미가 없다. 이 형식은 교환되는 정보의 문자 집합에 일부 제한 사항이 적용된다.
안전하지 않은 예약된 문자는 반드시 “% 인코딩”을 사용하여 에스케이프 처리해야 한다
[RFC3986]. 즉, 하나의 문자는 %HH 문자열로 대체되어야 한다. 여기서 HH는 글자
ASCII 코드의 16진법 표현을 나타낸다.

# 7.4.3.1. 요청문 application/x-www-form-urlencoded의 직렬화 지침

다음은 XML과 application/x-www-form-urlencoded 포맷 간 매핑을 위한 일반 규칙
이다:

- 가. POST 요청에서 이 직렬화를 활용할 경우, 요청의 본문에 데이터가 포함되지만,
- URL에는 포함되지 않는다. 이를 위해 Content-Type:
- application/x-www-form-urlencoded이 사용된다.
- 나. 요소 중 하나가 복합 타입일 경우, URL 인코딩 데이터에는 단순 타입의 자식 하위
- (또는 하위 하위) 요소만이 포함된다.
- 다. XML 계층 구조 문제가 없을 때 인코딩은 다음과 같을 것이다.
- subelement1=valueA&
- subelement2=valueB&
- attribute=valueC


application/x-www-form-urlencoded의 사용은 각 API에 대해 사례별로 지정되어야
한다. 이는 테이블을 통해 문서화해야 한다. 그 결과로 XML 계층 레벨이 제거된다.

application/x-www-form-urlencoded 본문에는 첫 <?xml version="1.0"
encoding="UTF-8" ?> 표시나 네임스페이스 또는 schemaLocations 선언이 없다.

# 7.5. 국제화

XML 직렬화: REST 요청/응답에서 국제화는 XML 본문의 UTF-8 인코딩을 사용하여 이
루어진다.

16

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

Content-Type: application/xml;

<?xml version="1.0" encoding="UTF-8"?>
<tns:example>
…..
</tns:example>

JSON 직렬화의 경우, application/json [RFC4627]에 명시된 바와 같이 UTF-8 인코딩
이 기본으로 사용된다.

Content-Type: application/json
Content-Transfer-Encoding: 8bit
<json UTF-8 data>

application/x-www-form-urlencoded 직렬화의 경우, 국제화 지원이 보다 제한적이다.
[RFC1738]과 [HTML_FORMS]에 따라 영숫자 ASCII 문자[0-9, a-z, A-Z]와 일부 기타
문자($-_.+!*'())만이 직접 포함될 수 있다. 다른 안전하지 못한 예약된 문자도 교환될 수
있지만, 반드시 이스케이프 처리되어야 한다(",?, etc.).

아래 예시와 같이, 이것은 POST/PUT 요청문의 GET/DELETE 쿼리 매개변수와
application/x-www-form-urlencoded 본문에도 적용된다.

Content-Type: application/x-www-form-urlencoded
message=quedar%EDamos+ma%F1ana&address=621444448

바이너리 데이터(binary data) 교환을 위해 base64가 Content-Transfer-Encoding으로
채택된다.

7.6. 하위 호환성

API의 진화는 구 API 버전을 사용하는 클라이언트를 위해 하위 호환성을 제공해야 한
다. 동일한 릴리즈(release)(즉 대대적 개정) 내의 이전 업그레이드(즉, 사소한 개정)에
대해서도 하위 호환성(backward compatibility )이 보장되어야 한다.

![image](/image/placeholder)


(그림 7-1) 구 API 버전을 사용하는 클라이언트

7.6.1. XML 기반 API

수신된 API 요청을 지원하기 위해, 서버 측에서는 API에서 다음과 같은 지침을 따라야
한다.

17

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

# 1) 데이터 타입 – 요소(Elements):

• XML 시퀀스/선택 내에서 새로운 요소를 포함한 새로운 버전의 데이터 타입을 생
성할 수 있지만, 항상 옵션이 될 것이다(minOccurs=0).

- 예: “wapsupport”라는 새로운 요소가 포함되지만, 옵션으로 포함된다. 이전 매
개변수(brand, model)는 유지된다.

<xsd:complexType name="UserTerminalInfoType">
<xsd:sequence>
<xsd:element name="brand" type="xsd:string"/>
<xsd:element name="model" type="xsd:string" />
<xsd:element name="wapsupport" type="xsd:string" minOccurs="0"/>
</xsd:sequence>
</xsd:complexType>

- 예: 가능성 있는 새로운 세 번째 선택이 포함된다.

<xsd:complexType name="AChoiceType">
<xsd:choice>
<xsd:element name="choice1" type="xsd:string"/>
<xsd:element name="choice2" type="xsd:string"/>
<xsd:element name="choice3" type="xsd:string"/>
</xsd:choice>
</xsd:complexType>

• 새로운 버전의 데이터 타입이 생성되면서 일부 특성 또는 매개변수의 카디널리티
(cardinality)가 바뀌지만, 항상 필수에서 옵션으로 바뀌고 옵션에서 필수로는 바뀌
지 않는다.

- 예: barnd와 model이 이제 옵션이 되었다.

<xsd:complexType name="UserTerminalInfoType">
<xsd:sequence>
<xsd:element name="brand" type="xsd:string" minOccurs="0 "/>
<xsd:element name="model" type="xsd:string" minOccurs="0 "/>
</xsd:sequence>
</xsd:complexType>

• REST에 대하여 새로운 특성이 정의될 수 있다. 하지만 항상 옵션이 될 것이다
(use=”required” 부재).

- 예: “lastUpdated”라는 새로운 속성이 포함되지만 옵션으로 포함된다.

<xsd:complexType name="UserTerminalInfoType">
<xsd:sequence>
<xsd:element name="brand" type="xsd:string" minOccurs="0 "/>
<xsd:element name="model" type="xsd:string" minOccurs="0 "/>
</xsd:sequence>
<xsd:attribute name="lastUpdated" type="xsd:string" use="optional"/>
</xsd:complexType>

18

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

# 2) 데이터 타입 – 열거형(Enumerations):

• 새로 열거형 값이 포함될 수 있지만, 항상 이전 값을 유지한다.

- 예: 새로운 값이 열거형(pound)에 포함되고, 기존에 존재하던 다른 두 개의 값
은 유지된다.

<xsd:simpleType name="CurrencyType">
<xsd:restriction base="xsd:string">
<xsd:enumeration value="euro"/>
<xsd:enumeration value="dollar"/>
<xsd:enumeration value="pound"/>
</xsd:restriction>
</xsd:simpleType>

- 


# 3) 작업 처리(Operations):

• 작업 처리 내용이 진화하면서 새로운 매개변수가 추가될 수 있다. 하지만 새 매개
변수는 항상 옵션이 될 것이다. 호환성을 위해 기존 매개변수는 항상 유지될 것이
다.

- 예: 기존 작업 과정에 새로운 선택적 입력 매개변수 “maxItems”가 포함된다.

![image](/image/placeholder)


(그림 7-2) 작업 하위 호환성

새로운 작업 처리 내용이 추가될 수 있지만, 호환성을 위해 기존 작업 처리 내용은 항
상 유지될 것이다.

# 7.6.2. JSON 기반 API

XML 기반 API 요청에 대해 위의 고려 사항이 적용된다. JSON의 경우, 하위 호환성을
위해 이전 API 버전의 기존 매개변수가 API 규격에서 유지될 것이다.

# 7.7. 상위 호환성, 확장성

API는 새로운 API 버전에 대한 상위 호환성을 제공하도록 설계되어야 한다. 이 호환성
은 통상 다음의 두 가지 방식으로 동일한 릴리즈의 업그레이드 간에 적용된다:

- l 기존 클라이언트에 응답을 반환하는 업그레이드 된 서버
- l 기존의 업그레이드 되지 않은 API 서버에 요청을 하는 새로운 클라이언트 버전


19

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

부 록 Ⅰ

# CoAP 동작 방식 사례

CoAP 프로토콜은 저전력, 고손실 네트워크 및 소용량,소형 노드에 사용될 수 있는 특
수한 웹 전송 프로토콜이다. HTTP와는 구조상 다른 방식으로 동작하지만, RESTful 사상
을 따르고 있기 때문에, RESTful 구조를 갖는 기존 HTTP 프로토콜과도 쉽게 변환 및 연
동이 될 수 있다.

CoAP은 기본적으로 UDP와 같은 데이터그램 방식의 트랜스포트 계층 위에서 비동기적
으로 전송되는 방식이다. 때문에 신뢰성 있는 전달을 위한 재전송 및 타이머 관리를 옵
션으로 포함하고 있다. 보안을 위해서는 UDP 계층과 CoAP 계층 사이에
DTLS(Datagram Transport Layer Security) 계층이 사용될 수 있다.

CoAP은 확인형(confirmable), 비확인형(non-confirmable), 승인(acknowledgement),
리셋(reset)의 4가지 메시지 타입을 정의하고 있고, CoAP 메시지는 HTTP와 같이 요청
(request)과 응답(response) 방식으로 처리된다.

| CoAP Request 예 | CoAP Response 예 | CoAP 요청/응답 과정 예 |
| --- | --- | --- |
| CON [0xbc90] GET /temperature (Token 0x71) | ACK [0xbc90] 2.05 Content (Token: 0x71) Content-Format:text/plain;charset=ut f-8 22.5 C | ![image](/image/placeholder)
 <figcaption><p>Chart Type: line</p></figcaption><table><thead><tr><td></td><td>ACK(Oxbc90)</td><td>ACK(0xbc90)</td><td>ACK(0x71)</td></tr></thead><tbody><tr><td>item_01</td><td>2.05Intensity (arbitrary units)</td><td>2.05Intensity (arbitrary units)</td><td>22.5Intensity (arbitrary units)</td></tr></tbody></table> |


# - CoAP Request 내용

- l Request의 의미 : GET /temperature
- l CON은 “Confirmable”의 의미로, 서버로부터 확인 메시지 요청하는 것이며, 16진수
- 값 0xbc90는 서버 확인 응답 시 사용할 “message ID”


# - CoAP Response 내용

- l “ACK”는 클라이언트 요청에 대한 응답을 의미
- l 2.05 Content 는 상태코드로 HTTP에서의 “HTTP’s 200 OK”과 동일
- l “Content-Format”은 CoAP 옵션 사항으로 HTTP Content-Type 헤더와 같은 용도
- 로 사용
- l “22.5 C” 문자열은 payload로 HTTP에서는 “entity-body”라고 부름


20

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

부 록 Ⅱ
참조 문헌

# [CoAP]

“The Constrained Application Protocol”, Z. Shelby, K. Hartke, C. Bormann,
June 2014, https://tools.ietf.org/html/rfc7252

# [Fielding]

“Architectural Styles and the Design of Network-based Software
Architectures”, Roy Fielding, 2000, URL:

http://www.ics.uci.edu/~fielding/pubs/dissertation/top.htm

# [JSON]

Java Script Object Notation, URL:http://www.json.org/

# [RFC1738]

“Uniform Resource Locations”, ”, T. Berners-Lee, L. Masinter, M. McCahill,
December 1994, URL: http://www.ietf.org/rfc/rfc1738.txt

# [RFC2616]

Hypertext Transfer Protocol -- HTTP/1.1”, R. Fielding et. al, June 1999,
http://www.ietf.org/rfc/rfc2616.txt

# [REST_NetAPI_Guidelines]

Guidelines for RESTful Network APIs, OMA

# [RESTAPI_Design_Rulebook]

REST API Design Rulebook, Mark Masse, O’Reilly Media, 2012.

21

TTAK.KO-10.0771/R1

정보통신단체표준(국문표준)

# 표준 작성 공헌자

# 표준 번호 : TTAK.KO-10.0771/R1

이 표준의 제정․개정 및 발간을 위해 아래와 같이 여러분들이 공헌하였습니다.

| 구분 | 성명 | 위원회 및 직위 | 연락처 (E-mail 등) | 소속사 |
| --- | --- | --- | --- | --- |
| 표준(과제) 제안 | 전종홍 | PG605 부의장 | hollobit@etri.re.kr | ETRI |
| 표준 초안 작성자 | 전종홍 | PG605 부의장 | hollobit@etri.re.kr | ETRI |
| 표준 초안 에디터 | 전종홍 | PG605 부의장 | hollobit@etri.re.kr | ETRI |
| 표준 초안 검토 | 이승윤 | 웹 프로젝트그룹 의장 | syl@etri.re.kr | ETRI |
| 표준 초안 검토 |  | 외 프로젝트그룹 위원 |  |  |
| 표준안 심의 | 박승민 | 소프트웨어/콘텐츠 기술위원회 의장 | minpark@etri.re.kr | ETRI |
| 표준안 심의 |  | 외 기술위원회 위원 |  |  |
| 사무국 담당 | 김영화 | - | ykim@tta.or.kr | TTA |
| 사무국 담당 | 이혜진 | - | hjlee@tta.or.kr | TTA |


22

TTAK.KO-10.0771/R1



정보통신단체표준(국문표준)

WoT를 위한 RESTful API 지침
(RESTful API Guidelines for WoT)

| 발행인 : | 한국정보통신기술협회 회장 |
| --- | --- |
| 발행처 : | 한국정보통신기술협회 463-824, 경기도 성남시 분당구 분당로 47 Tel : 031-724-0114, Fax : 031-724-0109 |
| 발행일 : | 2015.12. |


