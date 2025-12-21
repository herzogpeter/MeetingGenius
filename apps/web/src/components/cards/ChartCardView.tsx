import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ChartCard } from '../../contracts'
import { SourcesList } from './SourcesList'

export function ChartCardView(props: { card: ChartCard }) {
  const { card } = props
  const data = card.props.points.map((p) => ({ label: p.label, value: p.value }))

  return (
    <div className="mgCardBody">
      {card.props.subtitle ? <div className="mgCardSubtitle">{card.props.subtitle}</div> : null}
      <div className="mgChart">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 10, right: 16, bottom: 10, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="label" />
            <YAxis />
            <Tooltip />
            <Line type="monotone" dataKey="value" stroke="#2f6fed" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <SourcesList sources={card.sources} />
    </div>
  )
}

