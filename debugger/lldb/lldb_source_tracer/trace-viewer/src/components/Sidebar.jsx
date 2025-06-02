import React from 'react';

const Sidebar = ({ events, onEventSelect, selectedEvent }) => {
  const getEventClass = (event) => {
    if (event === selectedEvent) {
      return `timeline-event event-selected event-${event.type.toLowerCase()}`;
    }
    return `timeline-event event-${event.type.toLowerCase()}`;
  };
  
  const formatTimestamp = (timestamp) => {
    return timestamp.split('.')[0]; // Remove milliseconds for display
  };
  
  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <h3>Execution Timeline</h3>
        <p>{events.length} events</p>
      </div>
      
      <div className="timeline-list">
        {events.map((event, index) => (
          <div 
            key={index}
            className={getEventClass(event)}
            onClick={() => onEventSelect(event)}
          >
            <div className="event-header">
              <span className="event-type">{event.type}</span>
              <span className="event-timestamp">{formatTimestamp(event.timestamp)}</span>
            </div>
            <div className="event-function">{event.function}</div>
            <div className="event-location">
              {event.source_file}:{event.line}
            </div>
            {event.type === 'CALL' && (
              <div className="event-message">{event.message}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

export default Sidebar;