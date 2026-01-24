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
    <div className="personas-section">
      <div className="section-header">
        <h3>Personas</h3>
        <button onClick={handleAdd} className="add-persona-btn">
          + Add Persona
        </button>
      </div>

      {showAddForm && (
        <PersonaForm
          onSave={(name, instructions) => {
            handleSaveNew(name, instructions)
            setShowAddForm(false)
          }}
          onCancel={() => setShowAddForm(false)}
        />
      )}

      {personas.length === 0 && !showAddForm ? (
        <div className="empty-state">
          <p>No personas configured. Add a persona to set up gateway instructions for authentication.</p>
        </div>
      ) : (
        <div className="personas-list">
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
      <PersonaEditModal
        persona={persona}
        onSave={onSave}
        onCancel={onCancel}
      />
    )
  }

  return (
    <>
      <div className="persona-card">
        <div className="persona-header">
          <h4>{persona.name}</h4>
          <div className="persona-actions">
            <button onClick={() => setShowModal(true)} className="manage-btn">
              Manage
            </button>
            <button onClick={onDelete} className="delete-btn">Delete</button>
          </div>
        </div>
      </div>

      {showModal && (
        <PersonaInstructionsModal
          persona={persona}
          onClose={() => setShowModal(false)}
          onEdit={() => {
            setShowModal(false)
            onEdit()
          }}
        />
      )}
    </>
  )
}

interface PersonaInstructionsModalProps {
  persona: Persona
  onClose: () => void
  onEdit: () => void
}

function PersonaInstructionsModal({ persona, onClose, onEdit }: PersonaInstructionsModalProps) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content persona-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Gateway Instructions: {persona.name}</h3>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <div className="persona-instructions">
            <pre>{persona.gateway_instructions || '(No instructions configured)'}</pre>
          </div>
        </div>
        <div className="modal-footer">
          <button onClick={onEdit} className="edit-btn">Edit</button>
          <button onClick={onClose} className="close-btn">Close</button>
        </div>
      </div>
    </div>
  )
}

interface PersonaEditModalProps {
  persona: Persona
  onSave: (name: string, instructions: string) => void
  onCancel: () => void
}

function PersonaEditModal({ persona, onSave, onCancel }: PersonaEditModalProps) {
  const [name, setName] = useState(persona.name)
  const [instructions, setInstructions] = useState(persona.gateway_instructions)

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-content persona-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Edit Persona: {persona.name}</h3>
          <button className="modal-close" onClick={onCancel}>×</button>
        </div>
        <div className="modal-body">
          <div className="persona-form">
            <div className="form-group">
              <label>Persona Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., reseller, internal, distributor"
              />
            </div>
            <div className="form-group">
              <label>Gateway Instructions</label>
              <textarea
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                placeholder={`1. Click on "Log In With My Nutanix" button
2. Wait for SSO page to load (URL should contain stage-my.nutanix.com)
3. Fill username field with env(LOGIN_USERNAME)
...`}
                rows={12}
              />
              <small className="form-hint">
                Step-by-step instructions for authentication/navigation. Use env(VARIABLE_NAME) for credentials.
              </small>
            </div>
          </div>
        </div>
        <div className="modal-footer">
          <button onClick={onCancel} className="close-btn">Cancel</button>
          <button onClick={() => onSave(name, instructions)} className="primary">
            Save
          </button>
        </div>
      </div>
    </div>
  )
}

interface PersonaFormProps {
  onSave: (name: string, instructions: string) => void
  onCancel: () => void
}

function PersonaForm({ onSave, onCancel }: PersonaFormProps) {
  const [name, setName] = useState('')
  const [instructions, setInstructions] = useState('')

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-content persona-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Add New Persona</h3>
          <button className="modal-close" onClick={onCancel}>×</button>
        </div>
        <div className="modal-body">
          <div className="persona-form">
            <div className="form-group">
              <label>Persona Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., reseller, internal, distributor"
              />
            </div>
            <div className="form-group">
              <label>Gateway Instructions</label>
              <textarea
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                placeholder={`1. Click on "Log In With My Nutanix" button
2. Wait for SSO page to load (URL should contain stage-my.nutanix.com)
3. Fill username field with env(LOGIN_USERNAME)
4. Click Continue button
5. Wait for password screen to load
6. Fill password field with env(LOGIN_PASSWORD)
7. Click login/submit button
8. Wait for redirect back to original application
9. Wait for text "Partner Central" to be visible on the page`}
                rows={12}
              />
              <small className="form-hint">
                Step-by-step instructions for authentication/navigation. Use env(VARIABLE_NAME) for credentials.
              </small>
            </div>
          </div>
        </div>
        <div className="modal-footer">
          <button onClick={onCancel} className="close-btn">Cancel</button>
          <button
            onClick={() => {
              if (name.trim()) {
                onSave(name.trim(), instructions)
              }
            }}
            className="primary"
            disabled={!name.trim()}
          >
            Add Persona
          </button>
        </div>
      </div>
    </div>
  )
}

export default PersonasSection
