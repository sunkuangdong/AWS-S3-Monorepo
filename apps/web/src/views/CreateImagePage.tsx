import type {
  ChangeEvent,
  FormEvent,
} from 'react'

import {
  AppHeader,
} from '../components/layout/AppHeader'
import type { AppPage } from '../components/layout/AppHeader'
import { useCreateImageViewModel } from '../viewmodels/useCreateImageViewModel'

function ImageIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
    >
      <rect x="3" y="4" width="18" height="16" rx="3" />
      <circle cx="8.5" cy="9" r="1.5" />
      <path d="m5.5 17 4.2-4.4 3.1 3.1 2.2-2.2 3.5 3.5" />
    </svg>
  )
}

function SparkleIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
    >
      <path d="M12 2.8c.6 4.8 3.1 7.3 7.9 7.9-4.8.6-7.3 3.1-7.9 7.9-.6-4.8-3.1-7.3-7.9-7.9C8.9 10.1 11.4 7.6 12 2.8Z" />
      <path d="M19 16.8c.2 1.6 1.1 2.5 2.7 2.7-1.6.2-2.5 1.1-2.7 2.7-.2-1.6-1.1-2.5-2.7-2.7 1.6-.2 2.5-1.1 2.7-2.7Z" />
    </svg>
  )
}

interface CreateImagePageProps {
  onNavigate: (page: AppPage) => void
}

export function CreateImagePage({
  onNavigate,
}: CreateImagePageProps) {
  const viewModel = useCreateImageViewModel()

  function handleFileChange(
    event: ChangeEvent<HTMLInputElement>,
  ): void {
    viewModel.selectFile(
      event.target.files?.[0] ?? null,
    )

    // 允许用户删除后再次选择同一文件。
    // Allow the same file to be selected again after removal.
    event.target.value = ''
  }

  function handleSubmit(
    event: FormEvent<HTMLFormElement>,
  ): void {
    event.preventDefault()
    void viewModel.generate()
  }

  return (
    <main className="app-shell">
      <AppHeader
        activePage="create"
        onNavigate={onNavigate}
      />

      <div className="creator-layout">
        <section className="creator-intro">
          <p className="eyebrow">CREATE WITH AI</p>
          <h1>把想象变成画面</h1>
          <p>
            用文字直接创作，或上传一张参考图，
            让 AI 理解它的主体、构图与风格后再创作。
          </p>

          <div className="mode-summary" aria-label="支持的创作模式">
            <span><strong>01</strong> 文字生成</span>
            <span><strong>02</strong> 参考图生成</span>
          </div>
        </section>

        <section className="creator-card" aria-labelledby="creator-title">
          <div className="card-heading">
            <div>
              <p className="section-kicker">创作工作台</p>
              <h2 id="creator-title">描述你想要的图片</h2>
            </div>
            <span className="size-chip">1024 × 1024</span>
          </div>

          <form className="creator-form" onSubmit={handleSubmit}>
            <div className="field-group">
              <div className="field-heading">
                <label htmlFor="creation-prompt">创作描述</label>
                <span>{viewModel.prompt.length}/400</span>
              </div>

              <textarea
                id="creation-prompt"
                value={viewModel.prompt}
                onChange={(event) =>
                  viewModel.setPrompt(event.target.value)
                }
                maxLength={400}
                rows={6}
                placeholder="例如：一只橘猫坐在窗台上，温暖的晨光，电影摄影风格"
                disabled={viewModel.isGenerating}
              />
            </div>

            <div className="field-group">
              <div className="field-heading">
                <label htmlFor="reference-image">参考图</label>
                <span>可选</span>
              </div>

              {viewModel.selectedFile && viewModel.previewUrl ? (
                <div className="selected-image">
                  <img
                    src={viewModel.previewUrl}
                    alt="已选择的参考图"
                  />
                  <div className="selected-image-copy">
                    <strong>{viewModel.selectedFile.name}</strong>
                    <span>
                      {(viewModel.selectedFile.size / 1024 / 1024).toFixed(2)} MB
                    </span>
                    <button
                      type="button"
                      onClick={viewModel.removeFile}
                      disabled={viewModel.isGenerating}
                    >
                      移除参考图
                    </button>
                  </div>
                </div>
              ) : (
                <label className="upload-zone" htmlFor="reference-image">
                  <span className="upload-icon"><ImageIcon /></span>
                  <span className="upload-copy">
                    <strong>点击选择参考图</strong>
                    <small>JPG、PNG 或 WebP，最大 10MB</small>
                  </span>
                  <span className="upload-action">选择图片</span>
                </label>
              )}

              <input
                id="reference-image"
                className="visually-hidden"
                type="file"
                accept="image/jpeg,image/png,image/webp"
                onChange={handleFileChange}
                disabled={viewModel.isGenerating}
              />
            </div>

            <button
              className="generate-button"
              type="submit"
              disabled={!viewModel.canGenerate}
            >
              <span className="button-icon"><SparkleIcon /></span>
              {viewModel.isGenerating ? '正在创作……' : '生成图片'}
            </button>
          </form>

          {viewModel.statusMessage && (
            <p className="status-message" aria-live="polite">
              <span className={viewModel.isGenerating ? 'status-dot is-active' : 'status-dot'} />
              {viewModel.statusMessage}
            </p>
          )}

          {viewModel.errorMessage && (
            <p className="error-message" role="alert">
              {viewModel.errorMessage}
            </p>
          )}
        </section>

        {viewModel.result && (
          <section className="result-card" aria-labelledby="result-title">
            <div className="result-heading">
              <div>
                <p className="section-kicker">本次创作</p>
                <h2 id="result-title">生成结果</h2>
              </div>
              <span className="completed-badge">已完成</span>
            </div>

            {viewModel.result.output_url ? (
              <div className="result-image-frame">
                <img
                  src={viewModel.result.output_url}
                  alt={viewModel.result.user_prompt}
                />
              </div>
            ) : (
              <div className="result-placeholder">
                图片地址暂时不可用
              </div>
            )}

            <div className="result-details">
              <div>
                <span>创作模式</span>
                <strong>
                  {viewModel.result.generation_type === 'image_to_image'
                    ? '参考图生成'
                    : '文字生成'}
                </strong>
              </div>
              <div>
                <span>图片尺寸</span>
                <strong>
                  {viewModel.result.width} × {viewModel.result.height}
                </strong>
              </div>
              {viewModel.result.output_url && (
                <a
                  href={viewModel.result.output_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  打开原图
                </a>
              )}
            </div>
          </section>
        )}
      </div>
    </main>
  )
}
