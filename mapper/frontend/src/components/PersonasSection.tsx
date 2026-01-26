import { useState } from 'react'
import './PersonasSection.css'

export interface Persona {
  name: string
  gateway_instructions: string
}

interface PersonasSectionProps {
  personas: Persona[]
  onChange: (personas: Persona[]) => void
}

function PersonasSection({ personas, onChange }: PersonasSectionProps) {
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [showAddForm, setShowAddForm] = useState(false)

  const handleAdd = () => {
    setShowAddForm(true)
  }

  const handleSaveNew = (name: string, instructions: string) => {
    const newPersonas = [...personas, { name, gateway_instructions: instructions }]
    onChange(newPersonas)
    setShowAddForm(false)
  }

  const handleUpdate = (index: number, name: string, instructions: string) => {
    const newPersonas = [...personas]
    newPersonas[index] = { name, gateway_instructions: instructions }
    onChange(newPersonas)
    setEditingIndex(null)
  }

  const handleDelete = (index: number) => {
    const newPersonas = personas.filter((_, i) => i !== index)
    onChange(newPersonas)
  }

  return (
    <div className="ps-container">
      <div className="ps-list">
        {personas.map((persona, index) => (
          <PersonaCard
            key={index}
            persona={persona}
            isEditing={editingIndex === index}
            onEdit={() => setEditingIndex(index)}
            onSave={(name, instructions) => handleUpdate(index, name, instructions)}
            onCancel={() => setEditingIndex(null)}
            onDelete={() => handleDelete(index)}
          />
        ))}
        
        {personas.length === 0 && !showAddForm && (
          <div className="ps-empty">
            <p>No personas configured</p>
          </div>
        )}
      </div>

      {!showAddForm ? (
        <button onClick={handleAdd} className="ps-add-btn">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="12" y1="5" x2="12" y2="19"/>
            <line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          Add Persona
        </button>
      ) : (
        <div className="ps-modal-overlay" onClick={() => setShowAddForm(false)}>
          <div className="ps-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ps-modal-header">
              <h3>Add New Persona</h3>
              <button className="ps-modal-close" onClick={() => setShowAddForm(false)}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="18" y1="6" x2="6" y2="18"/>
                  <line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
            </div>
            <PersonaForm
              onSave={(name, instructions) => {
                handleSaveNew(name, instructions)
                setShowAddForm(false)
              }}
              onCancel={() => setShowAddForm(false)}
            />
          </div>
        </div>
      )}
    </div>
  )
}

interface PersonaCardProps {
  persona: Persona
  isEditing: boolean
  onEdit: () => void
  onSave: (name: string, instructions: string) => void
  onCancel: () => void
  onDelete: () => void
}

function PersonaCard({ persona, isEditing, onEdit, onSave, onCancel, onDelete }: PersonaCardProps) {
  const [showModal, setShowModal] = useState(false)

  if (isEditing) {
    return (
      <div className="ps-modal-overlay" onClick={onCancel}>
        <div className="ps-modal" onClick={(e) => e.stopPropagation()}>
          <div className="ps-modal-header">
            <h3>Edit Persona: {persona.name}</h3>
            <button className="ps-modal-close" onClick={onCancel}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>
          <PersonaForm
            initialName={persona.name}
            initialInstructions={persona.gateway_instructions}
            onSave={onSave}
            onCancel={onCancel}
            isEdit
          />
        </div>
      </div>
    )
  }

  return (
    <>
      <div className="ps-card">
        <div className="ps-card-content">
          <div className="ps-card-icon">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
              <circle cx="12" cy="7" r="4"/>
            </svg>
          </div>
          <span className="ps-card-name">{persona.name}</span>
        </div>
        <div className="ps-card-actions">
          <button onClick={() => setShowModal(true)} className="ps-icon-btn" title="View Instructions">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
              <circle cx="12" cy="12" r="3"/>
            </svg>
          </button>
          <button onClick={onEdit} className="ps-icon-btn" title="Edit">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
          </button>
          <button onClick={onDelete} className="ps-icon-btn ps-danger" title="Delete">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
      </div>

      {showModal && (
        <div className="ps-modal-overlay" onClick={() => setShowModal(false)}>
          <div className="ps-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ps-modal-header">
              <h3>Gateway Instructions: {persona.name}</h3>
              <button className="ps-modal-close" onClick={() => setShowModal(false)}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="18" y1="6" x2="6" y2="18"/>
                  <line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
            </div>
            <div className="ps-modal-body">
              <div className="ps-instructions">
                <pre>{persona.gateway_instructions || '(No instructions configured)'}</pre>
              </div>
            </div>
            <div className="ps-modal-footer">
              <button onClick={() => setShowModal(false)} className="ps-btn ps-btn-secondary">Close</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

interface PersonaFormProps {
  initialName?: string
  initialInstructions?: string
  onSave: (name: string, instructions: string) => void
  onCancel: () => void
  isEdit?: boolean
}

function PersonaForm({ initialName = '', initialInstructions = '', onSave, onCancel, isEdit }: PersonaFormProps) {
  const [name, setName] = useState(initialName)
  const [instructions, setInstructions] = useState(initialInstructions)

  return (
    <>
      <div className="ps-modal-body">
        <div className="ps-form">
          <div className="ps-field">
            <label className="ps-label">Persona Name</label>
            <input
              type="text"
              className="ps-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., reseller, internal"
            />
          </div>
          <div className="ps-field">
            <label className="ps-label">Gateway Instructions</label>
            <textarea
              className="ps-textarea"
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder={`1. Click on "Log In With My Nutanix" button\n2. Wait for SSO page to load...`}
              rows={12}
            />
            <small className="ps-hint">
              Step-by-step instructions for authentication/navigation. Use env(VARIABLE_NAME) for credentials.
            </small>
          </div>
        </div>
      </div>
      <div className="ps-modal-footer">
        <button onClick={onCancel} className="ps-btn ps-btn-secondary">Cancel</button>
        <button
          onClick={() => {
            if (name.trim()) {
              onSave(name.trim(), instructions)
            }
          }}
          className="ps-btn ps-btn-primary"
          disabled={!name.trim()}
        >
          {isEdit ? 'Save Changes' : 'Add Persona'}
        </button>
      </div>
    </>
  )
}

export default PersonasSection
