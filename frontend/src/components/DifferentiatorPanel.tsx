// 메인화면_시안_설계도.md 5-2절.
// props 없는 정적 컴포넌트다. 이유:
// (1) 메인 화면은 프로젝트가 선택되기 전이라 조회할 대상이 없다.
// (2) API 호출을 추가하면 첫 화면 로딩이 느려지는데, 얻는 건 "예시 하나"뿐이다.
// 단, 하드코딩이므로 "실제 실행 사례"라는 캡션은 붙이지 않는다(설계도 8절 금지 사항) —
// 지어낸 예시에 그 문구를 붙이는 것은 이 프로젝트가 반대해온 행위이기 때문이다.
export default function DifferentiatorPanel() {
  return (
    <section className="diff-panel" aria-label="다른 AI와 무엇이 다른가">
      <h2 className="diff-title">다른 AI와 무엇이 다른가</h2>

      <article className="dcard">
        <h3 className="dcard-title">문장마다 출처가 붙습니다</h3>
        <p className="dcard-body">
          수집한 정보를 문장 하나 단위로 쪼개, 출처 URL · 조회일 · 신뢰도까지 함께 저장합니다.
        </p>
        <div className="fact-mini">
          <div className="fact-mini-head">
            <span className="tier tier-2차">2차</span>
            <span className="fact-mini-badge">채택 · 근거 4/5</span>
          </div>
          <p className="fact-mini-text">
            북미 시니어 인구 중 65세 이상 비중은 2030년 21%까지 증가할 전망이다.
          </p>
          <p className="fact-mini-meta">census.gov · 조회 2026-07-20</p>
        </div>
      </article>

      <article className="dcard">
        <h3 className="dcard-title">검증을 통과한 근거만 씁니다</h3>
        <p className="dcard-body">
          관련성과 근거지지도를 각각 채점해 세 단계로 판정합니다. 결과는 문서에 그대로 남습니다.
        </p>
        <div className="verify-grid">
          <div className="verify-cell verify-cell-ok">
            <span className="verify-cell-label">채택</span>
          </div>
          <div className="verify-cell verify-cell-warn">
            <span className="verify-cell-label">애매</span>
          </div>
          <div className="verify-cell verify-cell-no">
            <span className="verify-cell-label">기각</span>
          </div>
        </div>
      </article>

      <article className="dcard hi">
        <h3 className="dcard-title">읽는 과정이 전부 보입니다</h3>
        <p className="dcard-body">
          어떤 검색어로 어느 사이트를 읽고 있는지 실시간으로 흐릅니다. 블랙박스가 아닙니다.
        </p>
        <ul className="proc-log">
          <li>[검색] "북미 시니어 웨어러블 시장 규모"</li>
          <li>[본문읽기] census.gov/…</li>
          <li>[근거 저장] 채택 2 · 애매 1</li>
          <li>[검색] "웨어러블 헬스케어 경쟁사"</li>
        </ul>
      </article>
    </section>
  );
}
