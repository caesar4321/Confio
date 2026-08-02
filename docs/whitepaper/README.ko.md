# Confío: 라틴아메리카의 신뢰받는 디지털 달러 플랫폼

**라틴아메리카를 위한 달러 금융 — 사용자가 통제하는 돈, 신뢰를 통한 유통.**

Confío는 라틴아메리카의 달러 현실을 위해 만든 완전 오픈소스 비수탁형 금융 앱이다. 현지 법정화폐 접근, 수익형 달러, 송금, 결제, 급여, 토큰화 자산을 익숙한 모바일 경험에 결합하며 사용자가 크립토를 이해하도록 요구하지 않는다.

**글로벌 기준 문서 · 버전 4.0 · 2026년 7월**<br>
Julian Moon · 창업자 겸 CEO<br>
[confio.lat](https://confio.lat) · [GitHub](https://github.com/caesar4321/Confio)

*Lo tuyo, tuyo. · 속은 블록체인, 사용은 PayPal처럼.*

**권위 있는 원문:** 영어 문서만이 Confío 백서의 공식 원문이다. 이 번역은 편의를 위해 제공되며 영어보다 늦게 갱신될 수 있다. 내용이 다르면 영어 원문이 우선한다.

이 문서는 Confío의 제품 구조, 전략, 운영 모델과 주요 위험에 관한 현재 글로벌 기준이다. $CONFIO 배분과 베스팅은 별도 토크노믹스 문서가 정한다.

<details>
<summary><strong>목차</strong></summary>

1. [요약](#1-요약)
2. [시장 논리](#2-시장-논리)
3. [BNB Smart Chain 제품 시스템](#3-bnb-smart-chain-제품-시스템)
4. [BNB Smart Chain을 선택한 이유](#4-bnb-smart-chain을-선택한-이유)
5. [cUSD+: 움직일 수 있는 저축](#5-cusd-움직일-수-있는-저축)
6. [결제, 급여와 토큰화 자산](#6-결제-급여와-토큰화-자산)
7. [BNB Smart Chain의 $CONFIO](#7-bnb-smart-chain의-confio)
8. [지갑, 보안과 오픈소스 구조](#8-지갑-보안과-오픈소스-구조)
9. [사용자, 유통과 시장 진입](#9-사용자-유통과-시장-진입)
10. [사업 모델](#10-사업-모델)
11. [컴플라이언스와 운영 모델](#11-컴플라이언스와-운영-모델)
12. [위험과 완화책](#12-위험과-완화책)
13. [로드맵과 현재 상태](#13-로드맵과-현재-상태)
14. [법적 고지](#14-법적-고지)
15. [주석](#주석)

</details>

---

## 1. 요약

Confío는 라틴아메리카를 위한 완전 오픈소스 비수탁형 디지털 달러 앱이다. 사용자는 가스 토큰, 블록체인 주소, 거래소 화면을 다루지 않고 달러를 보유하고, 저축하고, 보내고, 쓰고, 투자할 수 있다. <sup>[3]</sup>

> **제품 논리**
>
> 라틴아메리카에서 승리할 소비자 달러 플랫폼은 사용자에게 크립토 전문가가 되라고 요구하지 않는다. 검증 가능한 온체인 소유권에 현대 핀테크 수준의 명확성, 복구, 현지 결제수단과 사람의 지원을 결합해야 한다. 승부는 기능 수가 아니라 유통, 신뢰, 현지 적합성에서 난다. Confío는 약 48만 명의 스페인어 창업자 채널, 수년간 공개적으로 쌓은 지역 관계, 현재까지 사실상 0인 유료 미디어 지출을 갖고 시작한다.

Confío의 제품 시스템은 모두 BNB Smart Chain에서 결제된다.

| 구성요소 | 역할 | 설계 |
| --- | --- | --- |
| USDT | 범용 입금·유동성·출금 레일 | 현지·국제 제공자가 BSC-USDT를 사용자 주소로 보내며, 직접 보유·전송하거나 cUSD+ 입출력에 사용한다. |
| cUSD+ | 주 달러 저축·거래 잔액 | USDY 기반 누적형 볼트 지분으로 저축, 송금, 결제, 급여에 쓰고 USDT로 상환할 수 있다. |
| Ondo Stocks | 적격 사용자의 토큰화 시장 접근 | 같은 앱 업데이트에서 매수·매도를 출시하고 BSC의 Ondo Global Markets로 결제한다. |
| $CONFIO | 커뮤니티·생태계 토큰 | 고정 공급 BEP-20이며 USDT 표시 온체인 프리세일을 사용한다. 사용자 달러 잔액의 담보가 아니다. |

단일 네트워크는 막연한 체인 선택이 아니다. Ondo Finance가 USDY, InstantManager, 가격 오라클, USDT 구독·상환 경로와 Global Markets를 BNB Smart Chain에 제공했고, Confío는 체인 전환과 유동성 분산을 없애기 위해 결제, 급여, 송금과 $CONFIO도 같은 네트워크로 통합했다. <sup>[7, 8, 10]</sup>

2026년 7월 23일 기준 전화 인증 완료 사용자는 8,004명이다. 177명은 정부 발급 신분증과 라이브 셀피를 제출해 Didit의 생체 확인과 얼굴 비교를 완료했으며 시작자 대비 완료율은 61.5%다. 푸시 도달 가능 기기는 2,094개이고 2,092개가 최근 30일 안에 사용됐다. 이는 독립 감사를 거치지 않은 내부 지표이며 funded user나 표준 MAU를 뜻하지 않는다. <sup>[14]</sup>

cUSD+ 볼트, 스폰서드 트랜잭션 델리게이트, $CONFIO 토큰, 프리세일·리워드·베스팅 볼트, 초대 에스크로, 가맹점 결제 계약과 급여 볼트는 BNB Smart Chain에 배포되고 소스가 검증됐다. 해당 구성요소는 단계적 노출 통제와 함께 프로덕션에 연결돼 있다. cUSD+는 Ondo permissioned 인프라에 등록되어 프로덕션 USDY, USDT, InstantManager와 오라클을 통합한다. <sup>[8, 9, 17]</sup>

## 2. 시장 논리

### 2.1 크립토 인지도가 아니라 달러 접근의 문제

라틴아메리카는 하나의 통화위기가 아니다. 현지통화 변동성, 저렴한 국경 간 결제, 안전한 달러 저축, 실용적인 지급·수취 등 필요가 다르다. 공통점은 신뢰할 수 있는 달러 단위에 대한 수요와 기존 접근의 마찰이다. 지역 스테이블코인 채택은 이 수요가 이미 온체인에 있음을 보여준다. <sup>[2]</sup>

| 시장 | 관찰되는 달러 수요 | 제품 의미 |
| --- | --- | --- |
| 아르헨티나 | 인플레이션, 자본통제와 *corralito*의 기억은 수익률만큼 접근권과 통제권을 중시하게 했다. <sup>[19]</sup> | 수탁 경계, 출금권, 가격과 규칙 변경을 특별히 명확히 해야 한다. |
| 베네수엘라 | 극심한 인플레이션으로 달러가 가치저장과 일상 결제 역할을 모두 한다. <sup>[20]</sup> | 즉각적인 달러 접근과 결제가 필요하지만 제재와 제공자 규칙은 엄격한 통제를 요구한다. |
| 볼리비아 | IMF는 사용 가능한 외환보유액이 거의 고갈되고 병행환율 격차가 커졌다고 평가했다. <sup>[21]</sup> | 투명한 현지가격과 상호운용 QR은 일상 유동성 문제를 해결한다. |
| 페루 | 가계는 수백억 달러의 외화예금을 보유하며 Yape, PLIN, QR이 모바일 결제를 보편화했다. <sup>[22]</sup> | 달러 수요를 교육할 필요 없이 익숙한 진입점과 이동 가능한 저축을 제공하면 된다. |
| 멕시코 | 외화예금과 연간 약 US$62.5B 송금은 저축·국경 간 수요를 증명한다. <sup>[23]</sup> | SPEI, 달러 잔액, 수익과 가족 송금을 하나로 묶을 수 있다. |
| 콜롬비아 | 미국이 송금의 절반 이상을 공급하고 약 280만 명의 베네수엘라인이 거주한다. <sup>[24, 25]</sup> | PSE·Nequi·은행 레일이 국제송금과 콜롬비아–베네수엘라 가족 송금을 연결한다. |
| 미국·스페인 | 미국은 남미 송금의 35.7%, 유럽은 36.2%(스페인 19.7%p)를 차지한다. <sup>[24]</sup> | 카드와 SEPA가 디아스포라 소득을 거래 화면 없이 수취인의 달러 잔액으로 연결해야 한다. |

결과는 지역 전체의 **달러 본능**이다. 사람들은 비싸고 비공식적이거나 불안정해도 USD 노출을 찾는다.

### 2.2 송금은 잔액을 만드는 기회

라틴아메리카·카리브해는 2025년 약 US$173.7B의 송금을 받았다. <sup>[1]</sup> Confío는 이를 일회성 전송이 아니라 달러 보유, cUSD+ 변동수익, 연락처 송금, 결제와 현지 출금으로 이어지는 금융관계의 시작으로 본다.

### 2.3 소비자 금융의 수렴

거래소, 핀테크, 지갑과 스테이블코인 기업이 달러 잔액, 수익, 카드, 송금, 토큰화 자산으로 수렴한다. 많은 경쟁자는 같은 크립토 사용자에게 캐시백을 쓴다. Confío는 복제하기 어려운 유통과 현지 신뢰, 국가별 레일로 경쟁한다. <sup>[15, 16]</sup>

### 2.4 더 깊은 문제: *falta de confianza*

은행 동결, 통화통제, 실패한 핀테크, 비공식 브로커, 숨은 스프레드와 투기형 플랫폼이 신뢰 부족을 만들었다. Confío는 기기에서 생성되고 서버가 보유하지 않는 키라는 검증 가능한 통제와, 스페인어 교육·명확한 가격·현지 결제·공개 리더십·맥락 있는 지원이라는 인간 신뢰를 결합한다. *Lo tuyo, tuyo*는 브랜드 약속이자 아키텍처 제약이다.

## 3. BNB Smart Chain 제품 시스템

| 사용자 행동 | 자산·계약 | 온체인 결과 |
| --- | --- | --- |
| 달러 입금 | USDT | 제공자가 사용자 BSC 주소에 USDT를 보낸다. |
| 저축 | cUSD+ 볼트 | InstantManager가 USDT를 USDY로 구독하고 볼트가 cUSD+를 발행한다. |
| 송금 | cUSD+ 또는 USDT | 적격 내부 수취인은 cUSD+, 그 외에는 원자적 상환 또는 직접 USDT를 받는다. |
| 가맹점 결제 | cUSD+ 또는 $CONFIO, 결제 재원은 cUSD+ 또는 USDT | 가맹점이 cUSD+ 또는 $CONFIO로 청구하고, 계약이 0.9%를 계산해 가맹점에 순액을 지급한다. |
| 급여 | cUSD+, 선택적 USDT 출금 | 기업이 에스크로를 채우고 승인된 델리게이트가 지급을 서명한다. |
| 토큰화 자산 | Ondo Global Markets | 적격 주문이 Ondo 견적·attestation으로 BSC에서 결제된다. |
| $CONFIO 프리세일 | USDT | 스폰서드 트랜잭션이 불변 가격곡선에서 배분을 산다. |
| 리워드 | RewardVault | 누적 권리가 DB에 기록되고 DEX 해제 뒤 온체인 청구된다. |

### 3.1 공개 BNB Smart Chain 배포

아래 계약은 모두 mainnet에 라이브이며 소스가 검증됐다.

| 계약 | 주소 |
| --- | --- |
| cUSD+ 볼트 프록시 | [`0x3C29417eb4314155e63d4C7D4507852b87763Ed1`](https://bscscan.com/address/0x3C29417eb4314155e63d4C7D4507852b87763Ed1#code) |
| 스폰서드 배치 델리게이트 | [`0xC06BD197b34a587026615C6AEd21301F5E99bc00`](https://bscscan.com/address/0xC06BD197b34a587026615C6AEd21301F5E99bc00#code) |
| $CONFIO 토큰 | [`0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8`](https://bscscan.com/token/0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8) |
| 프리세일 볼트 | [`0x1a2dD9b49987DE86dC96fC86c715b62aaDFf095c`](https://bscscan.com/address/0x1a2dD9b49987DE86dC96fC86c715b62aaDFf095c#code) |
| 리워드 볼트 | [`0x812b8d86952123bED0a33E92a76211cbbACDe730`](https://bscscan.com/address/0x812b8d86952123bED0a33E92a76211cbbACDe730#code) |
| 베스팅 볼트 | [`0xb873e4dbFdf25EcB0F663CA9154F7384d780bE7A`](https://bscscan.com/address/0xb873e4dbFdf25EcB0F663CA9154F7384d780bE7A#code) |
| 초대 에스크로 | [`0xeFF0Af29FcB8f010f3B1e58bd5bbA36AEad4D0d6`](https://bscscan.com/address/0xeFF0Af29FcB8f010f3B1e58bd5bbA36AEad4D0d6#code) |
| 가맹점 결제 | [`0x039Ebe91283c686F23F4C751600a39567967736D`](https://bscscan.com/address/0x039Ebe91283c686F23F4C751600a39567967736D#code) |
| 급여 볼트 | [`0x851cA801c3028D4C0e651d29803f8e35D86d7299`](https://bscscan.com/address/0x851cA801c3028D4C0e651d29803f8e35D86d7299#code) |

### 3.2 하나의 네트워크가 중요한 이유

저축, 결제, 급여, 토큰화 자산과 $CONFIO 사이에 bridge가 필요 없고, 하나의 EVM 주소와 스폰서드 가스 시스템을 쓴다. 단일 체인이라도 각 제품의 경제·법률·적격성 규칙은 다르다.

### 3.3 현지·국제 접근

Koywe는 7개 라틴아메리카 시장에서 은행이체, Alias/CVU, SPEI, 상호운용 QR, PSE/Nequi, PIX를 제공한다. Guardarian은 유로존 SEPA와 Visa, Mastercard, Apple Pay, Google Pay를 통한 USD 구매를 제공한다. <sup>[13]</sup>

## 4. BNB Smart Chain을 선택한 이유

### 4.1 제품이 Ondo 인프라를 따랐다

핵심 이유는 Ondo Finance다. cUSD+는 USDY를 중심으로 설계됐고 Ondo는 프로덕션 USDY, InstantManager, 오라클, USDT 경로, Global Markets를 BNB Smart Chain에 배포했다. 같은 네트워크는 저축과 토큰화 자산에 직접 permissioned 접근을 준다. <sup>[7, 8, 10, 18]</sup>

### 4.2 소비자 규모의 비용과 유동성

BNB Smart Chain은 넓은 USDT 유동성, 낮은 비용, 성숙한 EVM 인프라와 결제·지갑·DeFi·RWA 생태계를 제공한다. 체인 규모 자체가 수요를 만들지는 않는다. 사용자를 유지하는 잔액, 안정적 출금, 유통, 보안과 투명한 경제가 중요하다. <sup>[5, 6, 12]</sup>

### 4.3 네트워크·거버넌스 위험

네트워크 중단, 검증자 조정, 혼잡, 가스 변화, RPC 실패나 생태계 정책 변화는 가능하다. 스폰서십, 복수 RPC, 비상출금, 비수탁 소유와 공개 상태로 완화하지만 제거할 수 없다.

## 5. cUSD+: 움직일 수 있는 저축

cUSD+는 배포된 볼트가 보유한 USDY로 뒷받침되는 달러 표시 누적형 지분이다. 사용자는 share, gas, approval, oracle이 아니라 달러 잔액을 본다.

### 5.1 입금과 상환

USDT가 사용자 주소에 도착하면 스폰서드 배치가 승인과 볼트 호출을 수행하고 InstantManager가 USDY를 구독해 cUSD+를 발행한다. 출금 시 cUSD+를 소각하고 USDY를 상환해 USDT를 사용자·수취인·램프 주소로 직접 보낸다. 볼트가 permissioned USDY 구매자이며 사용자는 cUSD+를 보유한다.

### 5.2 누적 가치와 수익 배분

USDY 기준가격의 양의 상승분 중 85%는 cUSD+ holder 기준가에, 15%는 Confío 잉여에 배분된다. share 수가 아니라 share당 달러가치가 오른다. 수익은 변동하며 보장되지 않는다. <sup>[7, 11]</sup>

### 5.3 담보와 오라클 통제

볼트는 의무, 담보비율, 잉여를 공개하며 담보에 유리하게 반올림하고 수수료 회수를 증명된 잉여로 제한한다. owner는 담보 USDY를 가져갈 수 없다. 오라클 하락이나 임계치 이탈 시 가치 이동 경로가 중지된다.

### 5.4 주 거래잔액으로서의 저축

cUSD+는 송금, 결제, 급여 직전까지 가치가 누적된다. 수취인이나 경로에 부적합하면 원자적으로 USDT로 상환한다. USDT는 숨은 중간자산이 아니라 명시적 fallback이다.

## 6. 결제, 급여와 토큰화 자산

### 6.1 개인 간 송금

서버가 정확한 호출을 준비하고 사용자가 서명하며 Confío가 가스를 낸다. 적격 사용자에게 cUSD+, 다른 수취인에게 원자적 상환 USDT, 또는 raw USDT를 보낸다. Confío 플랫폼 수수료는 0%이며 법정화폐 제공자 수수료는 별도일 수 있다.

### 6.2 가맹점 결제

가맹점은 두 가지 단위 중 하나로 청구한다. 달러 잔액인 **cUSD+**, 또는 달러 금액이 아니라 토큰 수량으로 표시되는 **$CONFIO**다. 둘 다 BNB 스마트 체인에서 결제된다.

USDT를 그대로 보유한 고객도 달러 청구서를 결제할 수 있으며, cUSD+ 발행 자격이 없는 고객도 마찬가지다. 가맹점은 지불자가 지불한 것과 같은 토큰을 받는다. 즉 USDT는 지불자의 결제 수단이지 가맹점이 청구할 수 있는 세 번째 단위가 아니다.

계약이 0.9%를 계산해 순액을 지급하고 실제 발생 수수료만 누적한다. 백엔드가 정확한 결제 조건에 대해 단기 유효 서명을 발급하고, 계약은 invoice 식별자 자체에 결제 사실을 기록한다. 따라서 하나의 청구서는 한 번만 결제되며, 백엔드가 승인하지 않은 자는 그 식별자를 소진시킬 수 없다. 각 청구서에는 결제가 허용된 단일 네트워크도 기록되어, 같은 청구가 서로 다른 네트워크에서 두 번 결제될 수 없다. 승인과 결제는 원자적으로 실행된다.

### 6.3 급여·대량지급

기업은 cUSD+ 에스크로에 운영자금을 두고 델리게이트에게 특정 지급 서명을 허가한다. 수취인은 cUSD+ 또는 상환된 USDT를 받고 수수료 회계는 에스크로와 분리된다.

### 6.4 Ondo Stocks

같은 앱 업데이트에서 적격 사용자가 Ondo Global Markets 토큰화 상품을 사고판다. Confío는 disclosure와 견적을 표시하고 Ondo 실행과 별도로 매수·매도 각각 0.30%를 부과하며 attestation과 BSC 결제를 처리한다. 미국인은 대상이 아니다. <sup>[18]</sup>

## 7. BNB Smart Chain의 $CONFIO

### 7.1 고정 공급 토큰

$CONFIO는 10억 개 고정 공급의 비업그레이드 BEP-20이다. owner, minter, proxy, tax, blacklist, pause, freeze가 없고 전체 공급은 multipart treasury에 한 번 발행됐다. USDT, cUSD+, USDY, Ondo Stocks를 담보하지 않는다. <sup>[17]</sup>

### 7.2 온체인 프리세일

USDT 기반 불변 연속곡선은 0–4M CONFIO에서 US$0.20→0.30, 4–24M에서 US$0.30→0.70, 24–74M에서 US$0.70→1.30이다. 계약은 곡선 아래 적분값을 받고 분할구매 할인을 방지하며 충분한 CONFIO가 있을 때만 청구를 연다. <sup>[17]</sup>

### 7.3 리워드와 DEX 잠금 청구

적격 활동은 DB에 기록되어 실시간 곡선가격으로 CONFIO로 환산된다. DEX 출시 후 짧은 유효기간의 EIP-712 서명이 누적 권리와 기청구액 차이만 지급한다. Treasury가 signer, pause, funding을 통제하므로 trustless escrow가 아니며 사용자는 조정과 자금 제공을 신뢰해야 한다.

## 8. 지갑, 보안과 오픈소스 구조

### 8.1 비수탁형 지갑

EVM 키는 사용자 기기에서 생성되고 Confío 서버가 보유하지 않는다. 암호화 복구자료는 사용자 개인 클라우드를 위해 설계된다. <sup>[3, 4]</sup>

> **Ni siquiera nosotros**
>
> Confío는 사용자의 지갑 키를 보유하지 않아 일반 지갑거래를 사용자 대신 서명할 수 없다. 다만 제품 계약과 발행자산은 공개된 적격성, pause, freeze, upgrade, governance 통제를 가질 수 있다.

### 8.2 스폰서드 트랜잭션

EIP-7702 사용자 승인과 ownerless 배치 델리게이트로 사용자가 호출을 서명하고 Confío sponsor가 가스를 낸다. 서버 정책이 대상, selector, 금액, 수취인, deadline과 일일한도를 제한한다. <sup>[8, 17]</sup>

### 8.3 오픈소스와 공개 검증

앱, 백엔드, 계약, 배포기록과 테스트가 공개돼 있다. 보안은 unit, fork, invariant/fuzz, adversarial, differential, upgrade rehearsal 테스트, 소스 검증, multipart governance, 제한된 수수료 회수, 오라클 guard, pause, replay 방지, slippage와 canary rollout을 결합한다. 어떤 방법도 위험을 제거하지 않는다. <sup>[3, 8, 9, 17]</sup>

### 8.4 업그레이드와 거버넌스

cUSD+는 외부 Ondo 계약 변경에 대응하기 위해 업그레이드 가능하다. $CONFIO와 프리세일 곡선은 비업그레이드이며 결제·급여 관리권은 pause와 증명된 수수료 회수 같은 정의된 기능으로 제한된다.

## 9. 사용자, 유통과 시장 진입

### 9.1 현재 운영지표

| 지표 | 수치 | 정의 |
| --- | ---: | --- |
| 전화 인증 완료 | 8,004 | 전화 인증을 완료한 사용자 |
| Didit 인증 완료 | 177 | 정부 신분증과 라이브 셀피, 생체 확인·얼굴 비교 완료 |
| 신원인증 완료율 | 61.5% | Didit 시작자 중 완료 비율 |
| 푸시 도달 기기 | 2,094 | 현재 알림을 보낼 수 있는 기기 |
| 최근 30일 사용 | 2,092 | 표준 MAU가 아닌, 최근 사용된 도달 가능 기기 |

2026년 7월 23일의 비감사 내부 지표이며 모든 사용자가 funded, active, unique, eligible하다는 뜻이 아니다. <sup>[14]</sup>

### 9.2 신뢰가 유통 채널이다

창업자의 스페인어권 소셜 청중은 약 48만 명이다. 장점은 숫자보다 금융상품을 대상 사용자의 문화 언어로 반복해서 공개 설명하는 능력이다. Confío는 cashback 경쟁이 아니라 신뢰를 인증, 입금, 잔액 유지, 반복 결제와 추천으로 전환하며 지금까지 유료 미디어 지출은 사실상 0이다. <sup>[15]</sup>

### 9.3 국가별 출시

법정화폐 수단, 신원요건, USDY·Ondo Stocks 적격성, 제재, 출금과 지원은 시장별로 다르다. 마케팅상의 국기보다 검증된 제공자 역량과 법률·운영 준비를 따른다.

## 10. 사업 모델

| 수익원 | 현재 정책 |
| --- | --- |
| 개인 간 송금 | Confío 0%; 제공자 수수료 별도 가능 |
| 가맹점 | 계약이 집행하는 0.9% |
| 급여 | 에스크로와 분리된 0.9% |
| cUSD+ 수익 | 양의 USDY 상승분 15% Confío, 85% holder; 변동·비보장 |
| Ondo Stocks | 매수·매도 각각 0.30%, Ondo·제3자 비용과 별도 |
| 법정화폐 레일 | 실시간 견적·계약에 따른 Koywe 비용과 Guardarian revenue share |
| 미래 상품 | 별도 조건·승인에 따른 수수료 또는 revenue share |

## 11. 컴플라이언스와 운영 모델

**고객확인(Know Your Customer, KYC)**은 사용자 신원과 필요한 경우 거주지를 확인하는 절차다. **자금세탁방지(Anti-Money Laundering, AML)**는 제재, 사기, 자금세탁, 테러자금과 금지행위를 탐지·방지하는 제공자·거래 통제다.

Confío는 법정화폐 보관·환전, 신원확인과 permissioned 자산 접근을 관련 제공자가 수행하도록 설계됐으며 Confío에 법적 의무가 없다는 주장은 아니다. Didit은 정부 신분증과 라이브 셀피로 문서, 생체, 얼굴을 검사한다. Koywe 거래에서 사용자가 자발적으로 주소를 입력하면 동의 아래 Koywe에 제출해 제공자 측 검증을 받는다. Guardarian도 거주지 주소와 자체 적격성·제재·거래통제를 요구한다. 전화 또는 Didit 인증은 Koywe, Guardarian, Ondo 승인을 보장하지 않는다. <sup>[7, 10, 13, 18]</sup>

## 12. 위험과 완화책

| 위험 | 현재 완화 | 잔여 노출 |
| --- | --- | --- |
| 자산·발행자 | USDY 구조와 USDT 입출력을 공개 | depeg, issuer, custody, reserve, legal, redemption |
| 스마트계약 | 오픈소스, 검증 배포, 다층 테스트, 제한된 통제 | bug, integration, upgrade |
| 오라클 | 임계치 중지와 근거 기반 대응 | 잘못되거나 없는 데이터로 지연 |
| 유동성 | USDT 상환과 raw USDT fallback | Ondo·제공자·네트워크·컴플라이언스 지연 |
| 적격성 | 제품별 규칙과 cUSD+ 보유 | 제공자가 주소·거래를 제한 가능 |
| 키 복구 | 기기 생성과 개인 클라우드 | 기기·클라우드 손실이나 결함 |
| 거버넌스 | multipart 통제와 공개 기록 | 유해한 변경 또는 대응 실패 |
| BNB Chain | bridge 제거, 복수 RPC·비상출금 | 단일 네트워크 문제가 전체에 영향 |
| Fiat rails | Koywe·Guardarian 라이브 | 범위·가격·가용성 변화 |
| 규제 | 문서·셀피·주소·screening·geofence | 사기·불법금융을 제거하지 못함 |
| 토큰 | 고정 공급, 공개계약, 불변곡선, 별도 tokenomics | 집중, vesting, 유동성, 가격 변동 |
| 리워드 | 누적청구, 짧은 deadline, DEX lock | treasury가 signer·pause·withdrawal·funding 통제 |
| 지표 | 정의와 날짜 공개 | 초기 사용·잔액 집중 가능 |

## 13. 로드맵과 현재 상태

| 작업 | 완료 / 현재 | 다음 검증 지점 |
| --- | --- | --- |
| cUSD+ | mainnet proxy, Ondo 등록, 프로덕션 계약 연결 | 담보와 상환 신뢰성을 유지하며 확장 |
| 스폰서십 | ownerless EIP-7702 델리게이트와 서버정책 | canary 확대, 비용·신뢰성 측정 |
| 송금 | BSC cUSD+/USDT 백엔드·모바일 구현 | 통제된 출시와 유지사용 측정 |
| 가맹점 | 0.9% 계약 배포·프로덕션 연결 | 반복사용과 정산 측정 |
| 급여 | escrow, delegate 지급, USDT 출금과 앱 연결 | 기업 pilot |
| $CONFIO | 고정토큰과 연속곡선 프리세일 배포·연결 | 청구 전에 의무량 funding |
| 리워드 | RewardVault 배포, DEX까지 잠금 | DB 적립, signer·client·funding·unlock |
| Ondo Stocks | 같은 BSC 앱 버전에 매수·매도 포함 | 적격 사용자 출시와 실행 측정 |
| Fiat | Koywe 7개 시장, Guardarian SEPA·카드 | 검증된 제공자와 fallback 추가 |
| 유통 | 8,004 전화완료, 177 Didit, 청중 ≈48만, paid media 사실상 0 | funded user와 retained balance로 전환 |

### 13.1 측정 원칙

가입, 전화완료, 인증, funded user, 도달기기, 활성사용과 retained balance를 구분한다. cUSD+ TVL, USDT, 입금·상환·순유입, 평균·중앙 잔액, 유지율, fiat 기원 유입, 집중도, 가맹점·급여와 국가 cohort를 측정한다.

### 13.2 다음 검증

> **배포된 인프라에서 유지되는 사용으로**
>
> 다음 증명은 BNB Smart Chain에서의 지속적 소비자 채택이다. funded user, 반복입금, 안정적 상환, 유지되는 cUSD+ 잔액, USDT 유동성, 가맹점·급여 활동과 여러 시장의 측정 가능한 fiat 유입이다.

## 14. 법적 고지

이 문서는 정보·기술 참고용이며 투자, 법률, 세무, 회계, 금융 조언이나 투자설명서, 제안, 권유, 추천, 수익 약속이 아니다. 2026년 7월 31일의 설계와 상태를 반영하며 바뀔 수 있다.

USDT와 cUSD+는 은행예금이 아니고 예금보험 대상이 아니다. Stablecoin, tokenized note, smart contract, blockchain, oracle, fiat provider, market maker, custodian은 실패, 중단, 가치하락 또는 규칙 변경을 겪을 수 있다. cUSD+ 수익은 변동하며 USDY와 볼트에 의존한다. Ondo Stocks는 Ondo 조건, 견적, 적격성과 법률을 따르는 토큰화 금융상품이며 Confío를 통해 미국인에게 제공되지 않는다.

$CONFIO는 USDT, cUSD+, USDY, Ondo Stocks와 별개이며 명시적 최종조건이 없는 한 Confío의 담보, 수익, 지분, 자산, 이익에 대한 권리를 주지 않는다.

## 주석

1. IDB, 2025년 라틴아메리카·카리브해 송금 US$173.7B. https://www.iadb.org/en/blog/migration/remittances-latin-america-and-caribbean-ease-after-2025-surge
2. Chainalysis, 2025 LATAM crypto adoption. https://www.chainalysis.com/blog/latin-america-crypto-adoption-2025/
3. Confío 공개 저장소. https://github.com/caesar4321/Confio
4. Confío, “Por qué Confío no guarda tu dinero”.
5. BNB Smart Chain 문서. https://docs.bnbchain.org/bnb-smart-chain/introduction/
6. BNB Chain 수수료·네트워크 문서. https://docs.bnbchain.org/bnb-smart-chain/
7. Ondo, USDY Basics. https://docs.ondo.finance/general-access-products/usdy/basics
8. cUSD+ BSC 배포기록. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/DEPLOYMENT.md
9. BscScan cUSD+ proxy. https://bscscan.com/address/0x3C29417eb4314155e63d4C7D4507852b87763Ed1#code
10. USDY InstantManager 통합문서. https://docs.ondo.finance/developer-guides/usdy-instant-manager-integration
11. `CusdPlusVault.sol`. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/CusdPlusVault.sol
12. BNB Chain 개발자 생태계. https://www.bnbchain.org/en/developers
13. 2026년 7월 Confío 파트너 기록: Koywe, Guardarian.
14. 2026년 7월 23일 Confío 내부 운영지표, 비감사.
15. 2026년 7월 23일 창업자 채널 내부지표.
16. Benedetto Biondi, *The New Face Of Global Payments*, Forbes, 2026-07-06. https://www.forbes.com/councils/forbestechcouncil/2026/07/06/the-new-face-of-global-payments-onchain-consumer-finance-apps/
17. Confío BSC 계약과 배포기록. https://github.com/caesar4321/Confio/tree/main/contracts/cusd_plus
18. Ondo Stocks와 Global Markets API. https://ondo.finance/ondo-stocks
19. IMF, 아르헨티나 역사문서. https://www.imf.org/External/NP/ieo/2003/arg/
20. IMF WP 2022/206, 베네수엘라 실질 달러화. https://www.elibrary.imf.org/view/journals/001/2022/206/article-A001-en.xml
21. IMF, Bolivia 2025 Article IV. https://www.imf.org/en/publications/cr/issues/2025/06/02/bolivia-2025-article-iv-consultation-press-release-staff-report-and-statement-by-the-567384
22. SBS Perú, 2026년 2월 통화별 예금. https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Febrero/SF-2102-fe2026.PDF
23. Banco de México 및 IDB 2025 송금보고서. https://publications.iadb.org/publications/english/document/Remittances-to-Latin-America-and-the-Caribbean-in-2025-Adaptations-in-a-Context-of-Uncertainty.pdf
24. IDB, *Remittances to Latin America and the Caribbean in 2025*. https://publications.iadb.org/publications/english/document/Remittances-to-Latin-America-and-the-Caribbean-in-2025-Adaptations-in-a-Context-of-Uncertainty.pdf
25. UNHCR, *Global Report 2025 — Colombia*. https://www.unhcr.org/sites/default/files/2026-06/global-report-2025-situation-overview-colombia.pdf

### 문서 출처

권위 있는 영어 백서, 공개 저장소, BSC 배포기록, BNB Chain·Ondo 공식문서, Koywe·Guardarian 기록, 인용 문헌과 이번 업데이트를 위해 제공된 내부지표를 바탕으로 만든 편의 번역이다.
