import './styles.css'

function App() {
  return (
    <main className="app-shell">
      <section className="welcome-card" aria-labelledby="workbench-title">
        <p className="eyebrow">Evidence RAG Workbench</p>
        <h1 id="workbench-title">可信知识库工作台</h1>
        <p>
          上传个人资料，获得可追溯引用、可拒答的本地知识库问答。
        </p>
        <p className="status">骨架已就绪，知识库与问答能力将在后续里程碑加入。</p>
      </section>
    </main>
  )
}

export default App
